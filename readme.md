# 🔐 Sanitizador de Dados para LLMs — LGPD

Middleware local desenvolvido em Python para **identificar e sanitizar dados pessoais e informações sensíveis antes que sejam enviados para APIs de modelos de linguagem (LLMs)**.

O projeto foi desenvolvido com foco em **privacidade, minimização de dados e segurança**, utilizando técnicas de pseudonimização para substituir informações sensíveis por marcadores antes do envio ao modelo.

> **Objetivo:** permitir o uso de LLMs em documentos que podem conter informações pessoais sem expor diretamente esses dados ao modelo.

---

## 🎯 Problema

O uso de ferramentas de Inteligência Artificial em ambientes profissionais pode envolver o envio de informações como:

* CPF e CNPJ;
* nomes;
* e-mails;
* telefones;
* endereços;
* informações financeiras;
* dados de empresas;
* documentos internos;
* informações potencialmente sensíveis.

Enviar esses dados diretamente para uma API de IA pode aumentar o risco de exposição de informações pessoais ou corporativas.

O Sanitizador atua como uma camada intermediária:

```text
┌────────────────────┐
│ Documento original │
│ com dados pessoais │
└─────────┬──────────┘
          │
          ▼
┌─────────────────────────┐
│      Sanitizador        │
│                         │
│ Regex + validações      │
│ Termos personalizados   │
│ Detecção de resíduos    │
│ Dados sensíveis         │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│    Texto sanitizado     │
│                         │
│ CPF → [CPF_1]           │
│ Nome → [NOME_1]         │
│ Email → [EMAIL_1]       │
└─────────┬───────────────┘
          │
          ▼
┌────────────────────┐
│        LLM         │
│ recebe somente os  │
│ dados sanitizados  │
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ Resposta restaurada│
│ localmente         │
└────────────────────┘
```

---

## ✨ Principais funcionalidades

### 🔎 Detecção de dados

O sistema identifica diferentes tipos de informações, incluindo:

* CPF;
* CNPJ;
* cartões de crédito;
* e-mails;
* telefones;
* CEP;
* IP;
* URLs;
* valores monetários;
* nomes;
* endereços;
* datas de nascimento;
* contas e agências;
* RG;
* empresas;
* clientes;
* projetos;
* produtos.

A detecção combina **expressões regulares, validações específicas e listas de termos personalizadas**.

---

### 🛡️ Camadas de proteção

O projeto utiliza múltiplas camadas para reduzir o risco de vazamento:

1. Termos personalizados;
2. Detecção de campos rotulados;
3. Validação de CPF e CNPJ;
4. Algoritmo de Luhn para cartões;
5. Detecção de URLs e valores monetários;
6. Detecção opcional de entidades;
7. Verificação de dados que permaneceram no texto;
8. Bloqueio de dados potencialmente sensíveis;
9. Aprovação humana antes do envio;
10. Auditoria sem armazenamento dos dados pessoais.

---

## 🔄 Pseudonimização

Os dados encontrados são substituídos por identificadores:

```text
Nome: Maria Souza
CPF: 529.982.247-25
Email: maria@empresa.com.br
```

torna-se:

```text
Nome: [NOME_1]
CPF: [CPF_1]
Email: [EMAIL_1]
```

O mesmo dado recebe o mesmo marcador durante o processamento, permitindo que o modelo compreenda relações e repetições sem receber o valor original.

Por exemplo:

```text
João da Silva → [NOME_1]

João da Silva novamente → [NOME_1]
```

---

## 🤖 Integração com LLM

O Sanitizador pode funcionar como uma camada antes da chamada de um modelo de linguagem.

```text
Aplicação
    │
    ▼
Sanitizador
    │
    ├── Detecta dados
    ├── Sanitiza
    ├── Verifica resíduos
    └── Solicita aprovação
    │
    ▼
API do LLM
    │
    ▼
Resposta sanitizada
    │
    ▼
Restauração local
    │
    ▼
Aplicação
```

A integração com o provedor de LLM é desacoplada do motor de sanitização, permitindo substituir o provedor sem alterar a lógica principal.

---

## 🧪 Testes

O projeto possui **54 testes automatizados** cobrindo diferentes cenários do sanitizador e do pipeline.

Os testes verificam:

* validadores;
* diferentes tipos de dados;
* formatos de Markdown;
* detecção de vazamentos;
* normalização de dados;
* duplicidade de informações;
* bloqueio de dados sensíveis;
* isolamento do mapa de substituição;
* auditoria;
* integração com o pipeline.

Um dos testes mais importantes verifica que o LLM **nunca recebe os dados originais**.

Nesse teste, um modelo falso armazena tudo que recebe e o teste verifica se algum dado real conseguiu chegar até ele.

---

## 💻 Tecnologias

* **Python 3.9+**
* Expressões Regulares (Regex)
* `unittest`
* JSON
* APIs de LLM
* GitHub Actions
* CLI

O núcleo do sanitizador utiliza apenas a biblioteca padrão do Python.

---

## 🚀 Como executar

Clone o repositório:

```bash
git clone https://github.com/JVCO30/Sanitizador-LGPD.git
cd Sanitizador-LGPD
```

Verifique a versão do Python:

```bash
python --version
```

O projeto requer Python 3.9 ou superior.

### Executar em modo simulado

O modo simulado permite testar o pipeline sem enviar informações para uma API externa:

```bash
python pipeline_relatorio.py relatorio_exemplo.txt --simular
```

### Executar os testes

```bash
python -m unittest -v
```

---

## 📚 Uso como biblioteca

O sanitizador também pode ser utilizado diretamente em aplicações Python:

```python
from sanitizador import Sanitizador

sanitizador = Sanitizador()

texto = """
Meu nome é Maria Souza,
CPF 529.982.247-25
e-mail maria@empresa.com.br
"""

texto_sanitizado = sanitizador.sanitizar(texto)

print(texto_sanitizado)
```

Resultado:

```text
Meu nome é [NOME_1],
CPF [CPF_1]
e-mail [EMAIL_1]
```

---

## 🏗️ Estrutura

```text
Sanitizador-LGPD/
│
├── sanitizador.py
├── pipeline_relatorio.py
├── test_sanitizador.py
├── test_pipeline.py
├── termos.json
├── relatorio_exemplo.txt
├── SECURITY.md
├── LICENSE
└── .github/
    └── workflows/
```

### Responsabilidades

`sanitizador.py`
Motor principal de detecção, validação, sanitização e restauração.

`pipeline_relatorio.py`
Implementação do fluxo completo, incluindo auditoria, análise de resíduos, bloqueios e aprovação.

`test_sanitizador.py`
Testes do motor de sanitização.

`test_pipeline.py`
Testes do pipeline completo.

---

## ⚠️ Limitações

O projeto não garante que todos os dados pessoais serão identificados automaticamente.

Alguns dados podem depender de contexto ou de configurações específicas do negócio.

Por isso, o sistema possui:

* análise de resíduos;
* possibilidade de adicionar termos personalizados;
* bloqueio de determinados dados;
* aprovação humana antes do envio.

**A revisão humana continua sendo necessária antes do envio de informações para uma API externa.**

---

## 🔐 Segurança

Nunca utilize dados pessoais reais nos exemplos ou testes do repositório.

Arquivos contendo informações reais, chaves de API, logs e configurações privadas devem permanecer fora do Git.

Nunca coloque uma chave de API diretamente no código.

---

## ⚖️ Aviso

Este projeto é uma ferramenta técnica de apoio à proteção de dados e **não garante conformidade com a LGPD por si só**.

A conformidade depende também de aspectos jurídicos, organizacionais e técnicos, incluindo bases legais, políticas internas, contratos, gerenciamento de fornecedores e procedimentos de segurança.

---

## 👨‍💻 Sobre o projeto

Projeto desenvolvido como estudo prático de **backend, segurança, privacidade de dados, automação e integração com Inteligência Artificial**.

A proposta é explorar como aplicações podem utilizar LLMs reduzindo a exposição desnecessária de informações pessoais.

---

## 📄 Licença

Este projeto está disponível sob a licença MIT.
