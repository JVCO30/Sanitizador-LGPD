import json
import unittest

from sanitizador import Sanitizador, cpf_valido, cnpj_valido, luhn_valido


class TestValidadores(unittest.TestCase):
    def test_cpf(self):
        self.assertTrue(cpf_valido("529.982.247-25"))
        self.assertFalse(cpf_valido("111.111.111-11"))
        self.assertFalse(cpf_valido("529.982.247-24"))

    def test_cnpj(self):
        self.assertTrue(cnpj_valido("11.222.333/0001-81"))
        self.assertFalse(cnpj_valido("11.222.333/0001-82"))

    def test_luhn(self):
        self.assertTrue(luhn_valido("4539 1488 0343 6467"))
        self.assertFalse(luhn_valido("4539 1488 0343 6468"))


class TestSanitizador(unittest.TestCase):
    def setUp(self):
        self.s = Sanitizador()

    def test_cpf_formatado_e_sem_mascara(self):
        r = self.s.sanitizar("CPF 529.982.247-25 ou 52998224725")
        self.assertNotIn("529", r)
        # mesmo CPF (com e sem máscara) são valores diferentes de texto -> 2 marcadores
        self.assertIn("[CPF_1]", r)
        self.assertIn("[CPF_2]", r)

    def test_numero_solto_invalido_nao_e_mascarado(self):
        # 11 dígitos "soltos" e sem rótulo podem ser protocolo: exige dígito verificador válido
        self.assertIn("12345678900", self.s.sanitizar("Protocolo 12345678900"))

    def test_cpf_formatado_invalido_e_mascarado(self):
        # CPF digitado errado ainda identifica a pessoa: formato de CPF basta
        self.assertNotIn("123.456.789-00", self.s.sanitizar("CPF 123.456.789-00"))

    def test_email(self):
        r = self.s.sanitizar("Fale com ana.silva@exemplo.com.br")
        self.assertEqual(r, "Fale com [EMAIL_1]")

    def test_telefones(self):
        for tel in ("(31) 99876-5432", "+55 31 99876-5432", "31998765432", "3333-4444"):
            r = self.s.sanitizar(f"Tel {tel}")
            self.assertIn("[TELEFONE_", r, tel)

    def test_cnpj_e_cartao(self):
        r = self.s.sanitizar("CNPJ 11.222.333/0001-81 cartão 4539 1488 0343 6467")
        self.assertIn("[CNPJ_1]", r)
        self.assertIn("[CARTAO_1]", r)

    def test_nome_por_contexto(self):
        r = self.s.sanitizar("Meu nome é Maria Souza Lima e preciso de ajuda")
        self.assertEqual(r, "Meu nome é [NOME_1] e preciso de ajuda")

    def test_mesmo_valor_mesmo_token(self):
        r = self.s.sanitizar("a@x.com e depois a@x.com e b@x.com")
        self.assertEqual(r, "[EMAIL_1] e depois [EMAIL_1] e [EMAIL_2]")

    def test_restaurar_ida_e_volta(self):
        original = "Contato: ana@x.com, CPF 529.982.247-25"
        limpo = self.s.sanitizar(original)
        self.assertEqual(self.s.restaurar(limpo), original)

    def test_json_recursivo(self):
        dado = {"cliente": {"nome": "João Pereira", "cpf": "52998224725"},
                "itens": ["ligar 31 3333-4444"], "valor": 10.5}
        r = self.s.sanitizar_json(dado)
        texto = json.dumps(r, ensure_ascii=False)
        for sensivel in ("João", "52998224725", "3333-4444"):
            self.assertNotIn(sensivel, texto)
        self.assertEqual(r["valor"], 10.5)

    def test_payload_nao_vaza(self):
        p = self.s.montar_payload_llm("Meu nome é Carlos Alves, cpf 529.982.247-25")
        corpo = json.dumps(p, ensure_ascii=False)
        self.assertNotIn("Carlos", corpo)
        self.assertNotIn("529.982", corpo)

    def test_relatorio_sem_dados_pessoais(self):
        self.s.sanitizar("a@x.com 529.982.247-25")
        rel = json.dumps(self.s.relatorio())
        self.assertNotIn("a@x.com", rel)
        self.assertEqual(self.s.relatorio()["EMAIL"], 1)

    def test_texto_sem_dados_fica_igual(self):
        t = "Explique o que é machine learning em 3 linhas."
        self.assertEqual(self.s.sanitizar(t), t)


class TestRegressaoRelatorio(unittest.TestCase):
    """Vazamentos encontrados em um relatório de teste real (markdown com campos rotulados)."""

    def setUp(self):
        self.s = Sanitizador()

    def assertMascarado(self, texto, *vazados):
        r = self.s.sanitizar(texto)
        for v in vazados:
            self.assertNotIn(v, r, f"vazou: {v!r} em {r!r}")
        return r

    def test_nome_em_markdown_negrito(self):
        self.assertMascarado("**Nome:** João da Silva", "João", "Silva")

    def test_nome_maiusculo_e_minusculo(self):
        self.assertMascarado("**Nome:** MARIA DE FÁTIMA OLIVEIRA", "MARIA", "OLIVEIRA")
        self.assertMascarado("Nome: joão da silva", "joão", "silva")

    def test_nome_em_prosa_nao_engole_a_frase(self):
        r = self.s.sanitizar("Responsável: aprovou o orçamento de março, conforme combinado.")
        self.assertIn("orçamento", r)

    def test_cpf_cnpj_invalidos_com_rotulo_ou_formato(self):
        self.assertMascarado("**CPF:** 12345678900", "12345678900")
        self.assertMascarado("**CNPJ:** 12345678000155", "12345678000155")
        self.assertMascarado("CNPJ 12.345.678/0001-90", "12.345.678")

    def test_data_nascimento_varios_formatos(self):
        for d in ("15/03/1998", "22-07-1995", "1990/12/04"):
            self.assertMascarado(f"**Data de nascimento:** {d}", d)

    def test_endereco_e_cep_sem_hifen(self):
        self.assertMascarado("**Endereço:** Av. Brasil Nº 450, Apt. 302", "Brasil", "450")
        self.assertMascarado("**CEP:** 39800123", "39800123")

    def test_dados_bancarios(self):
        self.assertMascarado("**Conta:** 001245-8\n**Agência:** 0045", "001245", "0045")

    def test_email_com_espacos_e_sem_tld(self):
        self.assertMascarado("maria.oliveira @ email.com", "maria.oliveira")
        self.assertMascarado("carlos.souza@email", "carlos.souza")

    def test_telefone_internacional_nao_vira_cartao(self):
        r = self.assertMascarado("Tel: +55 33 98888-1111", "98888")
        self.assertIn("[TELEFONE_", r)
        self.assertNotIn("CARTAO", r)
        self.assertNotIn("+[", r)  # o "+" faz parte do telefone

    def test_razao_social_e_nome_fantasia(self):
        self.assertMascarado("**Razão Social:** Alpha Tecnologia Ltda.\n**Nome Fantasia:** Alpha Tech",
                             "Alpha")


class TestEmpresaRotulo(unittest.TestCase):
    def test_empresa_rotulada(self):
        s = Sanitizador()
        r = s.sanitizar("**Empresa:** NovaHorizonte Serviços Digitais Ltda.")
        self.assertNotIn("NovaHorizonte", r)
        self.assertIn("[EMPRESA_1]", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
