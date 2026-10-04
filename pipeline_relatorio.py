"""
Pipeline seguro para resumir relatórios empresariais com LLM (foco LGPD)
========================================================================

Camadas de proteção, todas LOCAIS, antes de qualquer envio:

  1. Termos próprios   -> nomes de empresa, clientes, projetos, produtos (lista sua)
  2. Padrões (regex)   -> CPF, CNPJ, e-mail, telefone, cartão... (sanitizador.py)
  3. URLs e valores R$ -> mascarados (e restauráveis no resumo final)
  4. Detectores extras -> gancho para NER (spaCy/Presidio), opcional
  5. Verificação de resíduo -> alerta sobre o que PODE ter sobrado
  6. Bloqueio de dados sensíveis (art. 11 LGPD) -> exige decisão explícita
  7. Aprovação humana  -> você vê exatamente o que será enviado
  8. Isolamento        -> um mapa novo por documento, apagado ao final
  9. Auditoria         -> log só com hash/contagens, nunca dados pessoais

Uso rápido:
    python3 pipeline_relatorio.py relatorio.txt --termos termos.json --simular
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from sanitizador import Sanitizador

# --------------------------------------------------------------------------
# Padrões adicionais para contexto empresarial
# --------------------------------------------------------------------------
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')]*[^\s<>\"')\.,;:!?]", re.I)
VALOR = re.compile(
    r"R\$\s?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[.,]\d{1,2})?"
    r"(?:\s?(?:mil|milhão|milhões|bilhão|bilhões)\b)?",
    re.I,
)

# Dados pessoais sensíveis (LGPD art. 5º, II / art. 11) e grupos vulneráveis.
SENSIVEIS = re.compile(
    r"\b(sa[úu]de|doen[çc]a\w*|diagn[óo]stic\w*|laudo\w*|atestado\w*|depress\w*|"
    r"c[âa]ncer|hiv|religi\w*|sindicat\w*|partido\w*|orienta[çc][ãa]o sexual|"
    r"biometri\w*|etnia|ra[çc]a|menor(?:es)? de idade|crian[çc]a\w*|adolescente\w*)\b",
    re.I,
)
_CAP = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+"
CAPITALIZADO = re.compile(rf"\b{_CAP}(?:[ \t]+(?:d[aeo]s?[ \t]+)?{_CAP})+")
CAMEL_CASE = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)+\b")
COL_VALOR = re.compile(r"valor|pre[çc]o|total|montante|saldo|receita|faturamento|custo", re.I)
NUMERO_LONGO = re.compile(r"(?<![\w\[])\d{6,}(?![\w\]])")
TUDO_MAIUSCULO = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3,}(?:[ \t]+(?:(?:DE|DA|DO|DAS|DOS|E)[ \t]+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3,})+\b")
TOKEN = re.compile(r"\[[A-Z_]+_\d+\]")

INSTRUCOES = (
    "Resuma o relatório abaixo em português, de forma objetiva e estruturada. "
    "Trechos entre colchetes, como [EMPRESA_1] ou [VALOR_2], são marcadores anônimos "
    "de dados removidos: mantenha-os exatamente como estão, não tente adivinhar o que "
    "representam e não os explique."
)


class ErroDeRisco(Exception):
    """Levantado quando o pipeline decide NÃO enviar sem decisão humana."""


# --------------------------------------------------------------------------
# Sanitizador empresarial (estende o sanitizador base)
# --------------------------------------------------------------------------
class SanitizadorEmpresarial(Sanitizador):
    def __init__(
        self,
        termos: Optional[dict[str, Iterable[str]]] = None,
        mascarar_valores: bool = True,
        detectores_extras: Iterable[Callable[[str], list[tuple[str, str]]]] = (),
    ) -> None:
        super().__init__()
        self.mascarar_valores = mascarar_valores
        self.detectores_extras = list(detectores_extras)
        pares = [(tipo.upper(), t) for tipo, lista in (termos or {}).items() for t in lista if t.strip()]
        pares.sort(key=lambda p: len(p[1]), reverse=True)  # "Acme Brasil" antes de "Acme"
        self._regex_termos = [
            (tipo, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I), t) for tipo, t in pares
        ]

    def _marcar(self, tipo: str, valor: str) -> str:
        self.estatisticas[tipo] += 1
        return self._token(tipo, valor)

    def sanitizar(self, texto: str) -> str:
        if not isinstance(texto, str) or not texto:
            return texto
        texto = URL.sub(lambda m: self._marcar("URL", m.group(0)), texto)
        for tipo, rx, canonico in self._regex_termos:
            texto = rx.sub(lambda m, tipo=tipo, c=canonico: self._marcar(tipo, c), texto)
        for detector in self.detectores_extras:  # ex.: NER
            for trecho, tipo in detector(texto):
                if len(trecho) >= 2 and "[" not in trecho:
                    texto = texto.replace(trecho, self._marcar(tipo, trecho))
        if self.mascarar_valores:
            texto = self._mascarar_colunas_valor(texto)
            texto = VALOR.sub(lambda m: self._marcar("VALOR", m.group(0)), texto)
        return super().sanitizar(texto)

    def _mascarar_colunas_valor(self, texto: str) -> str:
        """Em tabelas markdown, mascara as células das colunas cujo cabeçalho indica dinheiro
        (Valor, Preço, Total...), mesmo sem "R$" na célula."""
        linhas = texto.split("\n")
        colunas = None
        for i, linha in enumerate(linhas):
            if not linha.lstrip().startswith("|"):
                colunas = None  # a tabela acabou
                continue
            if re.fullmatch(r"[\s|:\-]+", linha):
                continue  # linha separadora (| --- | ---: |)
            celulas = linha.split("|")
            if colunas is None:  # primeira linha da tabela = cabeçalho
                colunas = {j for j, c in enumerate(celulas) if COL_VALOR.search(c)}
                continue
            for j in colunas:
                if j < len(celulas):
                    conteudo = celulas[j].strip()
                    if conteudo and "[" not in conteudo:
                        celulas[j] = celulas[j].replace(conteudo, self._marcar("VALOR", conteudo), 1)
            linhas[i] = "|".join(celulas)
        return "\n".join(linhas)

    def apagar_mapa(self) -> None:
        """Descarta o mapa de reversão (o dado deixa de ser reidentificável por você)."""
        self._mapa.clear()
        self._reverso.clear()


# --------------------------------------------------------------------------
# Verificação de resíduo
# --------------------------------------------------------------------------
@dataclass
class Preparado:
    texto_limpo: str
    estatisticas: dict
    sensiveis: list[str] = field(default_factory=list)
    possiveis_nomes: list[str] = field(default_factory=list)
    numeros_longos: list[str] = field(default_factory=list)

    @property
    def tem_alertas(self) -> bool:
        return bool(self.sensiveis or self.possiveis_nomes or self.numeros_longos)


def verificar_residuo(texto_limpo: str) -> tuple[list[str], list[str], list[str]]:
    base = TOKEN.sub(" ", texto_limpo)  # marcadores já aplicados não contam como resíduo
    sens = sorted({m.group(0).lower() for m in SENSIVEIS.finditer(base)})
    nomes = sorted(
        set(CAPITALIZADO.findall(base)) | set(TUDO_MAIUSCULO.findall(base)) | set(CAMEL_CASE.findall(base))
    )[:100]
    nums = sorted(set(NUMERO_LONGO.findall(base)))[:100]
    return sens, nomes, nums


def dividir(texto: str, limite: int = 12000) -> list[str]:
    """Divide por parágrafos para relatórios longos (map-reduce)."""
    partes, atual = [], ""
    for par in texto.split("\n\n"):
        if atual and len(atual) + len(par) > limite:
            partes.append(atual)
            atual = ""
        atual += par + "\n\n"
    if atual.strip():
        partes.append(atual)
    return partes


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
class PipelineResumo:
    def __init__(
        self,
        termos: Optional[dict[str, Iterable[str]]] = None,
        mascarar_valores: bool = True,
        bloquear_sensiveis: bool = True,
        detectores_extras: Iterable[Callable[[str], list[tuple[str, str]]]] = (),
        auditoria_path: Optional[str] = None,
        limite_chars: int = 12000,
        ignorar_alertas: Iterable[str] = (),
    ) -> None:
        self.ignorar_alertas = {x.casefold() for x in ignorar_alertas}
        self.termos = termos
        self.mascarar_valores = mascarar_valores
        self.bloquear_sensiveis = bloquear_sensiveis
        self.detectores_extras = list(detectores_extras)
        self.auditoria_path = auditoria_path
        self.limite_chars = limite_chars

    def _novo_sanitizador(self) -> SanitizadorEmpresarial:
        # Mapa NOVO por documento: nada de correlação entre relatórios diferentes.
        return SanitizadorEmpresarial(self.termos, self.mascarar_valores, self.detectores_extras)

    def preparar(self, texto: str, san: Optional[SanitizadorEmpresarial] = None) -> Preparado:
        san = san or self._novo_sanitizador()
        limpo = san.sanitizar(texto)
        sens, nomes, nums = verificar_residuo(limpo)
        nomes = [n for n in nomes if n.casefold() not in self.ignorar_alertas]
        return Preparado(limpo, san.relatorio(), sens, nomes, nums)

    def resumir(
        self,
        texto: str,
        chamar_llm: Callable[[str], str],
        confirmar: Optional[Callable[[Preparado], bool]] = None,
        permitir_sensiveis: bool = False,
    ) -> str:
        san = self._novo_sanitizador()
        prep = self.preparar(texto, san)

        try:
            # 6) Bloqueio de dados sensíveis
            if prep.sensiveis and self.bloquear_sensiveis and not permitir_sensiveis:
                self._auditar(prep, "BLOQUEADO_SENSIVEL")
                raise ErroDeRisco(
                    f"Termos possivelmente sensíveis (art. 11 LGPD): {prep.sensiveis}. "
                    "Revise o texto ou chame com permitir_sensiveis=True se houver base legal."
                )

            # 7) Aprovação humana (obrigatória se houver qualquer alerta)
            if confirmar is not None:
                aprovado = confirmar(prep)
            elif prep.tem_alertas:
                self._auditar(prep, "BLOQUEADO_SEM_REVISAO")
                raise ErroDeRisco("Há alertas de resíduo e nenhuma função de confirmação foi fornecida.")
            else:
                aprovado = True
            if not aprovado:
                self._auditar(prep, "CANCELADO_PELO_USUARIO")
                raise ErroDeRisco("Envio cancelado pelo usuário.")

            # Envio (map-reduce se o texto for grande)
            partes = dividir(prep.texto_limpo, self.limite_chars)
            if len(partes) == 1:
                resposta = chamar_llm(f"{INSTRUCOES}\n\n---\n{partes[0]}")
            else:
                parciais = [
                    chamar_llm(f"{INSTRUCOES}\n\n(Parte {i}/{len(partes)})\n---\n{p}")
                    for i, p in enumerate(partes, 1)
                ]
                resposta = chamar_llm(
                    f"{INSTRUCOES}\n\nConsolide os resumos parciais abaixo em um único resumo.\n---\n"
                    + "\n\n".join(parciais)
                )

            # Marcadores inventados pelo LLM não podem ser restaurados: sinalizar.
            desconhecidos = [t for t in set(TOKEN.findall(resposta)) if t not in san._mapa]
            final = san.restaurar(resposta)
            if desconhecidos:
                final += f"\n\n[AVISO: marcadores não reconhecidos na resposta: {desconhecidos}]"
            self._auditar(prep, "ENVIADO", partes=len(partes))
            return final
        finally:
            san.apagar_mapa()  # 8) isolamento: mapa apagado ao final, inclusive em erro

    # 9) Auditoria sem dados pessoais
    def _auditar(self, prep: Preparado, decisao: str, partes: int = 0) -> None:
        if not self.auditoria_path:
            return
        registro = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decisao": decisao,
            "sha256_texto_enviado": hashlib.sha256(prep.texto_limpo.encode()).hexdigest(),
            "mascarados": prep.estatisticas,
            "alertas": {
                "sensiveis": len(prep.sensiveis),
                "possiveis_nomes": len(prep.possiveis_nomes),
                "numeros_longos": len(prep.numeros_longos),
            },
            "partes": partes,
        }
        with open(self.auditoria_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Confirmação humana via terminal e exemplos de LLM
# --------------------------------------------------------------------------
def confirmar_no_terminal(prep: Preparado) -> bool:
    print("\n" + "=" * 70)
    print("TEXTO QUE SERÁ ENVIADO AO LLM (já sanitizado):")
    print("=" * 70)
    print(prep.texto_limpo)
    print("=" * 70)
    print("Mascarados:", prep.estatisticas)
    def _mostrar(lista, limite=40):
        return lista[:limite] + ([f"... (+{len(lista) - limite})"] if len(lista) > limite else [])

    if prep.sensiveis:
        print("⚠ Termos sensíveis:", _mostrar(prep.sensiveis))
    if prep.possiveis_nomes:
        print("⚠ Possíveis nomes/empresas NÃO mascarados:", _mostrar(prep.possiveis_nomes))
    if prep.numeros_longos:
        print("⚠ Números longos (possíveis identificadores):", _mostrar(prep.numeros_longos))
    return input("\nEnviar? [s/N] ").strip().lower() in ("s", "sim", "y")


def llm_simulado(prompt: str) -> str:
    """Simula um LLM localmente (nada sai da máquina). Útil para testar o fluxo."""
    marcadores = sorted(set(TOKEN.findall(prompt)))[:4]
    return "Resumo simulado. Pontos citados: " + ", ".join(marcadores) + "."


def llm_anthropic(prompt: str) -> str:
    """Exemplo real. Requer `pip install anthropic` e a variável ANTHROPIC_API_KEY."""
    import anthropic

    msg = anthropic.Anthropic().messages.create(
        model="claude-sonnet-5-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# --------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Resumo seguro de relatório com LLM")
    ap.add_argument("arquivo", help="relatório em .txt/.md")
    ap.add_argument("--termos", help="JSON: {'EMPRESA': [...], 'CLIENTE': [...], 'PROJETO': [...]}")
    ap.add_argument("--simular", action="store_true", help="usa LLM simulado (nada é enviado)")
    ap.add_argument("--manter-valores", action="store_true", help="não mascara valores em R$")
    ap.add_argument("--auditoria", default="auditoria.jsonl")
    args = ap.parse_args()

    termos = json.load(open(args.termos, encoding="utf-8")) if args.termos else None
    ignorar = (termos or {}).pop("_ignorar", [])  # alertas inofensivos (ex.: nome da sua cidade)
    texto = open(args.arquivo, encoding="utf-8").read()
    pipeline = PipelineResumo(
        termos=termos,
        mascarar_valores=not args.manter_valores,
        auditoria_path=args.auditoria,
        ignorar_alertas=ignorar,
    )
    try:
        print(
            "\nRESUMO FINAL:\n",
            pipeline.resumir(texto, llm_simulado if args.simular else llm_anthropic, confirmar_no_terminal),
        )
    except ErroDeRisco as e:
        print("\n⛔", e)
