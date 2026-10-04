"""
Sanitizador de dados para LLMs (foco em LGPD)
=============================================

Camada de middleware que roda LOCALMENTE e remove/pseudonimiza dados pessoais
antes de qualquer texto ser enviado a uma API de IA.

Fluxo:
    texto bruto -> Sanitizador.sanitizar() -> texto com marcadores ([CPF_1]...)
                -> API do LLM (nunca vê o dado real)
                -> resposta com marcadores -> Sanitizador.restaurar() (local)

Somente biblioteca padrão do Python 3.9+.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------
# Validadores (reduzem falsos positivos: nem todo número de 11 dígitos é CPF)
# --------------------------------------------------------------------------
def cpf_valido(valor: str) -> bool:
    d = re.sub(r"\D", "", valor)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(d[j]) * (i + 1 - j) for j in range(i))
        dv = (soma * 10 % 11) % 10
        if dv != int(d[i]):
            return False
    return True


def cnpj_valido(valor: str) -> bool:
    d = re.sub(r"\D", "", valor)
    if len(d) != 14 or d == d[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(n) * p for n, p in zip(d[:pos], pesos))
        dv = 0 if soma % 11 < 2 else 11 - soma % 11
        if dv != int(d[pos]):
            return False
    return True


def luhn_valido(valor: str) -> bool:
    d = re.sub(r"\D", "", valor)
    if not 13 <= len(d) <= 19:
        return False
    soma = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        soma += n
    return soma % 10 == 0


# --------------------------------------------------------------------------
# Padrões. A ORDEM IMPORTA: do mais específico para o mais genérico.
# (tipo, regex, validador opcional)
# --------------------------------------------------------------------------
Padrao = tuple[str, "re.Pattern[str]", Optional[Callable[[str], bool]]]

def cpf_ou_formatado(valor: str) -> bool:
    """CPF válido OU número no formato de CPF (com . ou -), mesmo com dígito errado.
    Um CPF digitado errado ainda identifica a pessoa; só números 'soltos' exigem validação."""
    return cpf_valido(valor) or bool(re.search(r"[.\-]", valor))


def cnpj_ou_formatado(valor: str) -> bool:
    return cnpj_valido(valor) or bool(re.search(r"[./\-]", valor))


PADROES: list[Padrao] = [
    # aceita "maria @ email.com" (espaços) e "carlos@email" (sem .com): erros comuns de digitação
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+[ \t]?@[ \t]?[A-Za-z][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*"), None),
    ("CNPJ", re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"), cnpj_ou_formatado),
    ("CPF", re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)"), cpf_ou_formatado),
    # cartão: 14 a 19 dígitos e nunca logo após "+" (evita confundir telefone internacional)
    ("CARTAO", re.compile(r"(?<![\d+])(?:\d[ \-]?){13,18}\d(?!\d)"), luhn_valido),
    ("CEP", re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)"), None),
    (
        "TELEFONE",
        re.compile(r"(?<!\d)(?:\+?55[\s\-]?)?\(?\d{2}\)?[\s\-]?(?:9\d{4}|\d{4})[\s\-]?\d{4}(?!\d)"),
        None,
    ),
    ("TELEFONE", re.compile(r"(?<!\d)9?\d{4}-\d{4}(?!\d)"), None),
    ("IP", re.compile(r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"), None),
]

# Campos rotulados ("Nome: ...", "CPF: ...", "Conta: ..."): o RÓTULO revela o tipo do dado,
# então mascaramos o valor mesmo que seja inválido, minúsculo, MAIÚSCULO ou venha em markdown (**Nome:**).
_FIM = r"(?=[ \t]*(?:\r?\n|$|\||\*))"                 # o campo termina no fim da linha / célula
_NOME = r"[^\W\d_]+(?:[ \t.'’\-]+[^\W\d_]+){0,6}"      # até 7 palavras de letras
_LIVRE = r"[^\n|*]{2,200}?"
ROTULOS = [
    ("NOME", r"nome(?: completo)?|respons[áa]vel|titular|contato|representante|s[óo]cio", _NOME + _FIM),
    ("EMPRESA", r"empresa|raz[ãa]o social|nome fantasia", _LIVRE + _FIM),
    ("ENDERECO", r"endere[çc]o|logradouro", _LIVRE + _FIM),
    ("CPF", r"cpf", r"[\d.\-]{11,14}"),
    ("CNPJ", r"cnpj", r"[\d.\-/]{14,18}"),
    ("RG", r"rg|identidade", r"[\dXx.\-]{5,14}"),
    ("CEP", r"cep", r"[\d.\-]{8,10}"),
    ("CONTA", r"conta(?: corrente| poupan[çc]a)?|ag[êe]ncia", r"[\d.\-]{3,20}"),
    ("DATA_NASC", r"data de nascimento|nascimento", r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}"),
]
_PREFIXO = r"(?<![\wÀ-ÿ])(?:{})[ \t]*(?:\*+|_+)?[ \t]*:[ \t]*(?:\*+|_+)?[ \t]*"
PADROES_ROTULADOS = [
    (tipo, re.compile(_PREFIXO.format(rot) + "(" + val + ")", re.I | re.M)) for tipo, rot, val in ROTULOS
]

# Nomes não têm formato fixo: usamos "gatilhos" de contexto (heurística).
_PALAVRA = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+"
PADRAO_NOME = re.compile(
    r"(?i:\b(?:meu nome é|me chamo|sou o|sou a|nome:|cliente:|titular:|sr\.|sra\.|srta\.|dr\.|dra\.|prof\.)\s+)"
    rf"({_PALAVRA}(?:\s+(?:d[aeo]s?\s+)?{_PALAVRA}){{0,4}})"
)

# Chaves de JSON cujo valor é sempre considerado sensível.
CAMPOS_SENSIVEIS = {
    "nome": "NOME", "name": "NOME", "nome_completo": "NOME",
    "cpf": "CPF", "cnpj": "CNPJ", "rg": "RG",
    "email": "EMAIL", "e-mail": "EMAIL",
    "telefone": "TELEFONE", "celular": "TELEFONE", "phone": "TELEFONE",
    "endereco": "ENDERECO", "endereço": "ENDERECO", "address": "ENDERECO",
    "cep": "CEP", "cartao": "CARTAO", "cartão": "CARTAO",
    "data_nascimento": "DATA_NASC", "nascimento": "DATA_NASC",
}


class Sanitizador:
    """Pseudonimiza dados pessoais e guarda o mapa de reversão APENAS em memória local."""

    def __init__(self) -> None:
        self._mapa: dict[str, str] = {}      # token -> valor original
        self._reverso: dict[tuple[str, str], str] = {}  # (tipo, valor) -> token
        self._contadores: Counter[str] = Counter()
        self.estatisticas: Counter[str] = Counter()  # só contagens, sem dado pessoal

    # -- núcleo ------------------------------------------------------------
    def _token(self, tipo: str, valor: str) -> str:
        chave = (tipo, valor)
        if chave in self._reverso:  # mesmo valor -> mesmo marcador (preserva contexto)
            return self._reverso[chave]
        self._contadores[tipo] += 1
        token = f"[{tipo}_{self._contadores[tipo]}]"
        self._reverso[chave] = token
        self._mapa[token] = valor
        return token

    def sanitizar(self, texto: str) -> str:
        if not isinstance(texto, str) or not texto:
            return texto

        # 0) Campos rotulados: o rótulo ("CPF:", "Conta:", "Nome:") define o tipo
        for tipo, regex in PADROES_ROTULADOS:
            def troca_rot(m: re.Match, tipo=tipo) -> str:
                valor = m.group(1)
                if "[" in valor:  # já mascarado
                    return m.group(0)
                if tipo in ("NOME", "EMPRESA") and re.search(r"@|\d{4,}|https?://", valor):
                    return m.group(0)
                self.estatisticas[tipo] += 1
                ini = m.start(1) - m.start(0)
                return m.group(0)[:ini] + self._token(tipo, valor.strip())

            texto = regex.sub(troca_rot, texto)

        # 1) Nomes por contexto (mantém o gatilho, troca só o nome)
        def troca_nome(m: re.Match) -> str:
            self.estatisticas["NOME"] += 1
            prefixo = m.group(0)[: m.start(1) - m.start(0)]
            return prefixo + self._token("NOME", m.group(1))

        texto = PADRAO_NOME.sub(troca_nome, texto)

        # 2) Padrões estruturados
        for tipo, regex, validador in PADROES:
            def troca(m: re.Match, tipo=tipo, validador=validador) -> str:
                bruto = m.group(0)
                if validador and not validador(bruto):
                    return bruto  # parece, mas não é (ex.: CPF inválido)
                self.estatisticas[tipo] += 1
                return self._token(tipo, bruto)

            texto = regex.sub(troca, texto)
        return texto

    def restaurar(self, texto: str) -> str:
        """Troca marcadores pelos valores reais (executar só localmente)."""
        for token, original in self._mapa.items():
            texto = texto.replace(token, original)
        return texto

    # -- JSON --------------------------------------------------------------
    def sanitizar_json(self, dado: Any) -> Any:
        """Percorre dict/list recursivamente. Chaves sensíveis são mascaradas por inteiro."""
        if isinstance(dado, dict):
            saida = {}
            for k, v in dado.items():
                tipo = CAMPOS_SENSIVEIS.get(str(k).lower())
                if tipo and isinstance(v, (str, int)) and v != "":
                    self.estatisticas[tipo] += 1
                    saida[k] = self._token(tipo, str(v))
                else:
                    saida[k] = self.sanitizar_json(v)
            return saida
        if isinstance(dado, list):
            return [self.sanitizar_json(i) for i in dado]
        if isinstance(dado, str):
            return self.sanitizar(dado)
        return dado

    def montar_payload_llm(self, mensagem_usuario: str, modelo: str = "modelo-exemplo") -> dict:
        """Monta o corpo JSON de uma chamada a LLM JÁ higienizado."""
        return {
            "model": modelo,
            "messages": [{"role": "user", "content": self.sanitizar(mensagem_usuario)}],
        }

    def relatorio(self) -> dict:
        """Log de auditoria seguro: tipos e quantidades, nunca os valores."""
        return dict(self.estatisticas)


# --------------------------------------------------------------------------
# Demonstração
# --------------------------------------------------------------------------
if __name__ == "__main__":
    s = Sanitizador()
    bruto = (
        "Meu nome é Maria Souza Lima, CPF 529.982.247-25, e-mail maria@empresa.com.br, "
        "telefone (31) 99876-5432. Pagou com o cartão 4539 1488 0343 6467. "
        "Empresa: 11.222.333/0001-81."
    )
    print("ORIGINAL :", bruto)
    limpo = s.sanitizar(bruto)
    print("SANITIZADO:", limpo)

    print("\nPayload que iria para a API:")
    print(json.dumps(s.montar_payload_llm(bruto), ensure_ascii=False, indent=2))

    resposta_llm = f"Olá {s._reverso[('NOME', 'Maria Souza Lima')]}, confirmei o contato em [EMAIL_1]."
    print("\nResposta do LLM  :", resposta_llm)
    print("Restaurada local :", s.restaurar(resposta_llm))
    print("\nAuditoria:", s.relatorio())

    registro = {"cliente": {"nome": "João Pereira", "cpf": "52998224725"}, "obs": "ligar para 31 3333-4444"}
    print("\nJSON sanitizado:", json.dumps(s.sanitizar_json(registro), ensure_ascii=False))
