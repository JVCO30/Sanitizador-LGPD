# 🔐 Sanitizador de Dados para LLMs — LGPD

Ferramenta em Python, executada **localmente**, que identifica e substitui dados pessoais por marcadores (`[CPF_1]`, `[EMAIL_1]`…) **antes** de um texto ser enviado a uma API de modelo de linguagem (LLM). A resposta do modelo é restaurada na sua máquina, e o modelo nunca vê o dado original.

> **Por que existe:** eu usava IA para resumir documentos e percebi que eles podiam conter CPF, CNPJ, cartões e outros dados que não deveriam sair da minha máquina. Em vez de deixar de usar IA, construí uma camada de proteção entre o documento e o modelo.

---

## 📋 Sumário

- [Como funciona](#-como-funciona)
- [O que detecta](#-o-que-detecta)
- [Pipeline de proteção](#-pipeline-de-proteção)
- [Como executar](#-como-executar)
- [Uso como biblioteca](#-uso-como-biblioteca)
- [Uso com um LLM real](#-uso-com-um-llm-real)
- [Testes](#-testes)
- [Estrutura do projeto](#-estrutura-do-projeto)
- [Limitações](#️-limitações)
- [Segurança](#-segurança)
- [Sobre o desenvolvimento](#-sobre-o-desenvolvimento)
- [Próximos passos](#-próximos-passos)
- [Licença](#-licença)

---

## 🔄 Como funciona

```
Documento original ──► Sanitizador (local) ──► Texto com marcadores
                                                      │
                                       revisão e aprovação humana
                                                      │
                                                      ▼
                                                API do LLM
                                          (só recebe [CPF_1], [NOME_1]…)
                                                      │
                                                      ▼
                    Resposta com marcadores ──► Restauração local ──► Resposta final
```

O mesmo valor sempre recebe o mesmo marcador dentro de um documento, então o modelo entende repetições e relações sem conhecer os dados reais.

Exemplo real da execução de `python sanitizador.py`:

```
ORIGINAL  : Meu nome é Maria Souza Lima, CPF 529.982.247-25, e-mail maria@empresa.com.br,
            telefone (31) 99876-5432. Pagou com o cartão 4539 1488 0343 6467.
            Empresa: 11.222.333/0001-81.

SANITIZADO: Meu nome é [NOME_1], CPF [CPF_1], e-mail [EMAIL_1], telefone [TELEFONE_1].
            Pagou com o cartão [CARTAO_1]. Empresa: [CNPJ_1].

Resposta do LLM : Olá [NOME_1], confirmei o contato em [EMAIL_1].
Restaurada local: Olá Maria Souza Lima, confirmei o contato em maria@empresa.com.br.
```

> Os dados dos exemplos são fictícios.

---

## 🔎 O que detecta

O projeto tem duas camadas:

| Camada | Arquivo | Função |
|---|---|---|
| **Sanitizador base** | `sanitizador.py` | Dados pessoais estruturados, campos rotulados e nomes por contexto |
| **Sanitizador empresarial** | `pipeline_relatorio.py` | Estende o base com termos próprios, URLs, valores em R$ e verificações de risco |

### Sanitizador base (`Sanitizador`)

| Tipo | Como é detectado |
|---|---|
| **CPF** | Regex + validação dos dígitos verificadores. Números formatados (com `.` ou `-`) são mascarados mesmo com dígito errado, porque um CPF digitado errado ainda identifica a pessoa |
| **CNPJ** | Regex + validação dos dígitos verificadores (mesma regra do CPF para números formatados) |
| **Cartão** | Regex de 14 a 19 dígitos + algoritmo de Luhn |
| **E-mail** | Regex, tolerante a erros comuns de digitação (`maria @ email.com`, `carlos@email`) |
| **Telefone, CEP, IP** | Regex |
| **Campos rotulados** | O rótulo define o tipo: `Nome:`, `Empresa:`, `Endereço:`, `CPF:`, `CNPJ:`, `RG:`, `CEP:`, `Conta:`/`Agência:`, `Data de nascimento:`. Funciona com maiúsculas, minúsculas e Markdown (`**Nome:**`) |
| **Nomes por contexto** | Gatilhos como "meu nome é", "me chamo", "Sr.", "Dra.", "Cliente:", "Titular:" |
| **JSON** | `sanitizar_json()` percorre dicionários e listas e mascara chaves sensíveis (`nome`, `cpf`, `email`, `telefone`…) |

### Sanitizador empresarial (`SanitizadorEmpresarial`)

| Tipo | Como é detectado |
|---|---|
| **Termos próprios** | Lista sua em JSON (`termos.json`): empresas, clientes, projetos, produtos, bairros… Termos maiores são aplicados antes dos menores ("Acme Brasil" antes de "Acme") |
| **URLs** | Regex |
| **Valores em R$** | Regex e, em tabelas Markdown, células de colunas cujo cabeçalho indica dinheiro (Valor, Preço, Total, Saldo…) |
| **Entidades (NER)** | Apenas um **gancho** (`detectores_extras`) para plugar spaCy, Presidio etc. Nenhum detector de entidades vem incluído |

---

## 🛡️ Pipeline de proteção

`PipelineResumo` (em `pipeline_relatorio.py`) aplica estas camadas, todas locais, antes de qualquer envio:

1. **Termos próprios** (`termos.json`);
2. **Padrões** (regex e validadores) do sanitizador base;
3. **URLs e valores em R$** mascarados;
4. **Detectores extras** (gancho opcional para NER);
5. **Verificação de resíduos:** alerta sobre o que *pode* ter sobrado (possíveis nomes, números longos, termos sensíveis);
6. **Bloqueio de dados sensíveis** (art. 5º, II e art. 11 da LGPD): termos como saúde, diagnóstico, religião ou menores de idade interrompem o envio, a menos que você chame com `permitir_sensiveis=True`;
7. **Aprovação humana:** você vê exatamente o que será enviado. Se houver alertas e nenhuma função de confirmação, o envio é bloqueado;
8. **Isolamento:** um mapa novo por documento, apagado ao final (inclusive em caso de erro);
9. **Auditoria:** um log `.jsonl` com data, decisão, hash SHA-256 do texto enviado e contagens, **nunca** dados pessoais.

Outros comportamentos:

- Textos longos são divididos por parágrafos (12.000 caracteres por parte) e resumidos em etapas, com uma consolidação final.
- Se o LLM inventar um marcador que não existe no mapa, a resposta final traz um aviso em vez de restaurar algo errado.

Exemplo de saída do pipeline com o relatório fictício do repositório (`--simular`):

```
Mascarados: {'DOCUMENTO': 1, 'BAIRRO': 5, 'VALOR': 14, 'NOME': 10, 'EMPRESA': 7, 'ENDERECO': 8,
             'CPF': 9, 'CNPJ': 3, 'CEP': 8, 'CONTA': 2, 'DATA_NASC': 5, 'EMAIL': 22, 'TELEFONE': 12}
⚠ Possíveis nomes/empresas NÃO mascarados: ['Banco Exemplo', 'Governador Valadares', 'Nome Fantasia', ...]

Enviar? [s/N]
```

---

## 🚀 Como executar

Requisitos: **Python 3.9+** (desenvolvido para 3.9 ou superior e executado com 3.12). O núcleo usa apenas a biblioteca padrão.

```bash
git clone https://github.com/JVCO30/Sanitizador-LGPD.git
cd Sanitizador-LGPD
```

**Demonstração do sanitizador:**

```bash
python sanitizador.py
```

**Pipeline completo em modo simulado** (nada é enviado para fora da máquina):

```bash
python pipeline_relatorio.py relatorio_exemplo.txt --termos termos.json --simular
```

O programa mostra o texto sanitizado e os alertas, e pede confirmação no terminal (`Enviar? [s/N]`). Responda `n` para cancelar.

**Opções da linha de comando:**

| Opção | Efeito |
|---|---|
| `--termos ARQUIVO.json` | Carrega a sua lista de termos próprios |
| `--simular` | Usa um LLM simulado local |
| `--manter-valores` | Não mascara valores em R$ |
| `--auditoria ARQUIVO` | Caminho do log de auditoria (padrão: `auditoria.jsonl`) |

**Formato do `termos.json`:**

```json
{
  "EMPRESA": ["Acme Brasil", "Acme"],
  "CLIENTE": ["Supermercados Horizonte"],
  "PROJETO": ["Projeto Aurora"],
  "_ignorar": ["Minas Gerais"]
}
```

Cada chave (exceto `_ignorar`) vira o tipo do marcador (`[EMPRESA_1]`). A chave `_ignorar` lista termos inofensivos que não devem gerar alerta de resíduo (por exemplo, o nome da sua cidade).

---

## 📚 Uso como biblioteca

**Sanitizador base:**

```python
from sanitizador import Sanitizador

s = Sanitizador()
limpo = s.sanitizar("Meu nome é Maria Souza Lima, CPF 529.982.247-25.")
print(limpo)   # Meu nome é [NOME_1], CPF [CPF_1].

resposta_do_llm = "Olá [NOME_1]!"
print(s.restaurar(resposta_do_llm))   # Olá Maria Souza Lima!
print(s.relatorio())                  # só contagens, sem dados pessoais
```

**Pipeline com confirmação humana:**

```python
from pipeline_relatorio import PipelineResumo, llm_simulado, confirmar_no_terminal

pipeline = PipelineResumo(
    termos={"EMPRESA": ["Acme Brasil"]},
    auditoria_path="auditoria.jsonl",
)
resumo = pipeline.resumir(
    texto,
    chamar_llm=llm_simulado,          # qualquer função: str -> str
    confirmar=confirmar_no_terminal,  # você aprova antes do envio
)
```

---

## 🤖 Uso com um LLM real

A integração com o provedor é desacoplada: o pipeline recebe qualquer função `chamar_llm(prompt: str) -> str`, então trocar de provedor não exige mexer no motor de sanitização.

O repositório traz um exemplo, `llm_anthropic`, que:

- exige `pip install anthropic` (dependência **opcional**, só para essa função);
- lê a chave da variável de ambiente `ANTHROPIC_API_KEY`;
- usa o modelo definido dentro da própria função (altere conforme sua conta).

Sem `--simular`, o script usa essa função:

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sua-chave"   # nunca coloque a chave no código
python pipeline_relatorio.py relatorio.txt --termos termos.json
```

---

## 🧪 Testes

```bash
python -m unittest -v
```

Saída esperada nesta versão: `Ran 48 tests … OK`.

Os testes cobrem validadores, tipos de dados, formatos Markdown, detecção de resíduos, bloqueio de dados sensíveis, isolamento do mapa, auditoria e o pipeline completo. Um teste importante usa um LLM falso que guarda tudo o que recebe e verifica que nenhum dado real chegou até ele.

---

## 🏗️ Estrutura do projeto

```
Sanitizador-LGPD/
├── sanitizador.py          # motor: validadores, padrões, sanitização e restauração
├── pipeline_relatorio.py   # termos próprios, verificação de resíduos, bloqueios, aprovação e auditoria
├── test_sanitizador.py     # testes do motor
├── test_pipeline.py        # testes do pipeline
├── termos.json             # exemplo de termos (dados fictícios)
├── relatorio_exemplo.txt   # relatório fictício para demonstração
├── SECURITY.md             # política de segurança
├── LICENSE                 # licença MIT
└── .github/workflows/      # execução automática dos testes
```

---

## ⚠️ Limitações

Esta ferramenta **reduz** o risco de exposição, mas não o elimina:

- **Nomes não têm formato fixo.** Eles só são mascarados quando aparecem depois de um gatilho ("meu nome é", "Sr.", "Cliente:"), em um campo rotulado (`Nome:`) ou quando estão na sua lista de termos. Um nome solto no meio de um parágrafo pode passar.
- **Cidades, bancos e nomes de empresas sem rótulo** também dependem do `termos.json`. Na execução de exemplo, "Banco Exemplo" e "Governador Valadares" não foram mascarados e apareceram como alerta.
- **O verificador de resíduos gera falsos positivos.** Ele sinaliza sequências de palavras capitalizadas, então títulos como "Faturamento Janeiro" ou "Cadastro de Clientes" aparecem como "possíveis nomes". É de propósito: prefiro alertar demais a deixar passar.
- **A detecção de entidades (NER) não está implementada**, só o gancho para ela.
- **Marcadores aproximam, não garantem.** O contexto de um texto pode reidentificar alguém mesmo sem o dado direto.

Por isso a **revisão humana antes do envio é parte do projeto**, não um detalhe opcional.

---

## 🔐 Segurança

- Nunca use dados pessoais reais nos exemplos, testes ou no `termos.json` do repositório.
- O `.gitignore` já ignora `auditoria.jsonl` (`*.jsonl`), `.env` e a pasta `privado/`. Mantenha os seus termos reais e relatórios fora do Git.
- Nunca coloque uma chave de API no código; use variáveis de ambiente.
- Veja também o [SECURITY.md](SECURITY.md).

> ⚖️ **Aviso:** este projeto é uma ferramenta técnica de apoio e **não garante conformidade com a LGPD por si só**. A conformidade também depende de base legal, políticas internas, contratos com fornecedores e procedimentos de segurança.

---

## 👨‍💻 Sobre o desenvolvimento

Projeto pessoal, feito como estudo prático de privacidade de dados, regex, testes e integração com IA. Usei IA (Claude) como mentor durante o desenvolvimento e validei as soluções com testes.

Um aprendizado que ficou: meu primeiro detector de CPF/CNPJ só reconhecia números "limpos" e falhou com documentos reais, que trazem pontos, traços e barras. A correção foi tratar as variações de formatação (função `cpf_ou_formatado`) em vez de remendar só o caso que falhou.

---

## 🧭 Próximos passos

- Implementar um detector de entidades (NER) opcional usando o gancho existente;
- Aceitar mais formatos de entrada além de `.txt` e `.md`;
- Reduzir falsos positivos do verificador de resíduos;
- Separar o `termos.json` de exemplo do arquivo real de cada usuário.

---

## 📄 Licença

Distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE).
