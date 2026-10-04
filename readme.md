# Sanitizador de Dados para LLMs (foco em LGPD)

Camada de **middleware local** que higieniza textos antes de enviá-los a APIs de modelos de linguagem (LLMs). Dados pessoais e informações corporativas sensíveis são substituídos por marcadores anônimos (`[CPF_1]`, `[EMPRESA_2]`...) **antes** de qualquer dado sair do seu computador. A resposta do modelo é restaurada localmente.

```
texto bruto ──► sanitizador (local) ──► "Cliente [NOME_1], CPF [CPF_1]..." ──► LLM
                       │                                                       │
                       └── mapa marcador→valor (só em memória) ◄── restaurar ◄─┘
```

Somente biblioteca padrão do Python (3.9+). Nenhuma dependência obrigatória.

---

## Por que existe

Enviar nomes, CPFs, e-mails ou dados de clientes diretamente para uma API de IA pode violar princípios da LGPD (minimização, segurança, transferência internacional) e expor informações da empresa. Este projeto aplica **pseudonimização** (LGPD, art. 13, §4º) e **minimização** (art. 6º, III) na origem, e ainda exige **aprovação humana** antes do envio.

## O que é detectado

| Tipo | Como | Observação |
|---|---|---|
| CPF, CNPJ | regex + dígito verificador | Número formatado (`123.456.789-00`) ou após o rótulo `CPF:` é mascarado mesmo se inválido, pois um dado digitado errado ainda identifica a pessoa |
| Cartão de crédito | regex + algoritmo de Luhn | 14 a 19 dígitos |
| E-mail | regex | aceita `maria @ email.com` e `carlos@email` |
| Telefone, CEP, IP | regex | formatos brasileiros |
| URLs | regex | domínios internos revelam muito |
| Valores em R$ | regex | também colunas `Valor`/`Preço`/`Total` de tabelas markdown |
| Nomes, endereços, datas de nascimento, conta/agência, RG | **rótulos** (`Nome:`, `Endereço:`, `Conta:`...) | funciona com markdown (`**Nome:**`), MAIÚSCULAS e minúsculas |
| Empresas, clientes, projetos, produtos | **lista sua** (`termos.json`) | o que regex não consegue adivinhar |

O **mesmo dado em formatos diferentes recebe o mesmo marcador** (`João da Silva` = `joao da silva`; `123.456.789-00` = `12345678900`; `(33) 98888-1111` = `+55 33 98888-1111`), então o modelo ainda consegue perceber duplicatas sem saber quem é a pessoa.

## Camadas de proteção

1. Termos próprios (`termos.json`)
2. Campos rotulados (`Nome:`, `CPF:`, `Conta:`...)
3. Padrões com validação (CPF, CNPJ, Luhn)
4. URLs e valores monetários
5. Gancho opcional para NER (spaCy, Presidio)
6. **Verificação de resíduo**: alerta sobre nomes, CamelCase e números longos que sobraram
7. **Bloqueio de dados sensíveis** (art. 11 LGPD: saúde, religião, sindicato, menores...)
8. **Aprovação humana**: você vê o texto exato que será enviado
9. **Mapa novo por documento**, apagado ao final (mesmo em caso de erro)
10. **Auditoria** sem dados pessoais (hash e contagens)

---

## Instalação

```bash
git clone <seu-repositorio>
cd sanitizador-lgpd
python --version        # precisa ser 3.9 ou superior
```

Para usar a API real (opcional):

```bash
pip install anthropic
```

## Uso rápido (linha de comando)

```bash
# 1) Teste sem enviar nada (LLM simulado, tudo local)
python pipeline_relatorio.py relatorio_exemplo.txt --termos termos.exemplo.json --simular

# 2) Uso real (copie o exemplo e edite com os SEUS termos; termos.json fica fora do Git)
cp termos.exemplo.json termos.json
export ANTHROPIC_API_KEY="sua-chave"          # Windows PowerShell: $env:ANTHROPIC_API_KEY="sua-chave"
python pipeline_relatorio.py relatorio.txt --termos termos.json
```

O programa mostra o texto sanitizado e os alertas, e pergunta `Enviar? [s/N]`.

| Opção | Função |
|---|---|
| `arquivo` | relatório em `.txt` ou `.md` |
| `--termos` | JSON com os termos sensíveis do seu negócio |
| `--simular` | usa um LLM simulado local (nada é enviado) |
| `--manter-valores` | não mascara valores em R$ |
| `--auditoria` | arquivo do log de auditoria (padrão: `auditoria.jsonl`) |

> Nunca escreva a chave de API dentro do código.

## `termos.json`

O repositório traz `termos.exemplo.json`. Copie para `termos.json` (já listado no `.gitignore`) e preencha com os termos reais do seu negócio.

```json
{
  "EMPRESA": ["Nome da sua empresa", "Sigla"],
  "CLIENTE": ["Cliente A Ltda"],
  "PROJETO": ["Codinome do projeto"],
  "DOCUMENTO": ["REL-2026-00987"],
  "_ignorar": ["São Paulo", "Razão Social"]
}
```

- Cada chave vira o tipo do marcador (`"CLIENTE"` → `[CLIENTE_1]`). Crie as categorias que precisar.
- Inclua variações do nome (completo e abreviado). Termos mais longos têm prioridade.
- `_ignorar` lista alertas que você sabe que são inofensivos, para que a lista de resíduos mostre só o que importa.

## Uso como biblioteca

```python
from sanitizador import Sanitizador

s = Sanitizador()
limpo = s.sanitizar("Meu nome é Maria Souza, CPF 529.982.247-25, maria@empresa.com.br")
# 'Meu nome é [NOME_1], CPF [CPF_1], [EMAIL_1]'

resposta_llm = "Olá [NOME_1], confirmei [EMAIL_1]."
print(s.restaurar(resposta_llm))   # restauração local

s.sanitizar_json({"cliente": {"nome": "João", "cpf": "52998224725"}})
# {'cliente': {'nome': '[NOME_2]', 'cpf': '[CPF_1]'}}  (dict/list, recursivo; o mesmo CPF mantém o marcador)
s.relatorio()                       # {'NOME': 2, 'EMAIL': 1, 'CPF': 2}  (só contagens, acumuladas)
```

Pipeline completo:

```python
from pipeline_relatorio import PipelineResumo, confirmar_no_terminal, llm_anthropic, ErroDeRisco

pipeline = PipelineResumo(
    termos={"EMPRESA": ["Acme Brasil"]},
    ignorar_alertas=["São Paulo"],
    auditoria_path="auditoria.jsonl",
)
try:
    resumo = pipeline.resumir(texto, llm_anthropic, confirmar=confirmar_no_terminal)
except ErroDeRisco as e:
    print("Envio bloqueado:", e)
```

`chamar_llm` é qualquer função `str -> str`. Para usar outro provedor, basta trocar `llm_anthropic` pela sua.

## Testes

```bash
python -m unittest -v      # roda todos os arquivos test_*.py (54 testes)
```

Os testes cobrem validadores, cada tipo de dado, formatos de markdown, vazamentos já encontrados em relatórios de teste, normalização de duplicatas, bloqueio de dados sensíveis, isolamento do mapa e auditoria. O mais importante é `test_llm_nunca_ve_dado_real`: um LLM falso guarda tudo o que recebe e o teste verifica que nenhum dado real chegou lá.

## Estrutura

```
sanitizador.py          motor base (validadores, padrões, rótulos, classe Sanitizador)
pipeline_relatorio.py   fluxo completo (termos, resíduo, bloqueio, aprovação, auditoria, CLI)
test_sanitizador.py     testes do motor base
test_pipeline.py        testes do pipeline
termos.exemplo.json     modelo de termos (copie para termos.json e edite)
relatorio_exemplo.txt   relatório fictício de teste
SECURITY.md             como reportar falhas (sem dados reais!)
LICENSE                 MIT
.gitignore              mantém dados reais e logs fora do Git
.github/workflows/      testes automáticos (Python 3.9 a 3.13)
```

---

## Limitações (leia antes de usar com dados reais)

- **Regex não pega tudo.** Nomes sem rótulo ou gatilho ("Falei com a Ana") só são pegos se estiverem no `termos.json` ou se você conectar um NER. Por isso existem o alerta de resíduo e a aprovação humana.
- **Pseudonimizado não é anonimizado.** Enquanto o mapa existe em memória, o dado continua pessoal para quem o trata (LGPD, art. 13, §4º). O mapa nunca é gravado em disco nem enviado.
- **Reidentificação pelo contexto.** Cargo, cidade, data e fatos raros podem identificar alguém mesmo sem nome. Só a revisão humana resolve.
- **Dados sensíveis (art. 11)** são bloqueados por padrão e exigem decisão explícita (`permitir_sensiveis=True`) e base legal. O alerta é amplo e pode disparar em falsos positivos (ex.: "saúde financeira").
- **Valores sem `R$`** fora de tabelas com cabeçalho de valor não são mascarados.
- **Bairro, cidade e estado** não são mascarados por padrão. Adicione ao `termos.json` se necessário.
- **Formatos:** o script lê texto puro e markdown. Para Word ou PDF, extraia o texto antes.
- Sempre **revise o texto sanitizado** antes de aprovar o envio. Com dados reais, rode primeiro com `--simular`.

## Privacidade do repositório e contribuições

- **Todos os dados dos exemplos e dos testes são fictícios.**
- Guarde relatórios reais, `termos.json` e logs de auditoria fora do Git (o `.gitignore` já cobre `termos.json`, `*.jsonl` e a pasta `privado/`). Use `privado/` para seus arquivos reais.
- Antes de cada `git push`, confira com `git status` que nenhum arquivo com dado real foi adicionado.
- Em *issues* e *pull requests*, **nunca cole dados pessoais reais**. Use valores fictícios no mesmo formato.
- Novos padrões de detecção devem vir com teste. Um bom exemplo é o de placa de carro: adicione o regex em `PADROES` e um teste em `test_sanitizador.py`.

## Aviso legal

Este projeto é uma **medida técnica** de minimização e segurança, e **não garante conformidade com a LGPD por si só**. A conformidade também depende de base legal para o tratamento, contrato com o fornecedor da API (com treinamento desativado e retenção mínima), registro das operações, RIPD quando aplicável e validação do jurídico ou do encarregado (DPO). Isto não é aconselhamento jurídico.

## Licença

MIT. Veja o arquivo [`LICENSE`](LICENSE).
