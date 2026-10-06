# Política de segurança

## Reportando uma falha

Este projeto é uma ferramenta de higienização de dados. O tipo mais importante de falha é o
**falso negativo**: um dado pessoal que deveria ser mascarado e não foi.

Para reportar, abra uma *issue* ou use "Report a vulnerability" na aba Security do repositório.

**Nunca inclua dados pessoais reais** na descrição, em exemplos ou em capturas de tela.
Use dados fictícios com o mesmo formato (por exemplo, `123.456.789-09` em vez de um CPF real).

## O que esta ferramenta não promete

- Não garante conformidade com a LGPD, nem anonimização completa.
- Não detecta nomes ou termos sem formato previsível, a menos que estejam em `termos.json`.
- Sempre revise o texto sanitizado antes de enviá-lo a qualquer serviço externo.
