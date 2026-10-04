import json
import os
import tempfile
import unittest

from pipeline_relatorio import (
    ErroDeRisco, PipelineResumo, SanitizadorEmpresarial, dividir, llm_simulado, TOKEN, verificar_residuo,
)

TERMOS = {
    "EMPRESA": ["Acme Brasil", "Acme"],
    "CLIENTE": ["Supermercados Horizonte"],
    "PROJETO": ["Projeto Aurora"],
}

RELATORIO = (
    "Relatório trimestral da Acme Brasil. O cliente Supermercados Horizonte renovou o contrato "
    "de R$ 2.450.000,00 no Projeto Aurora. Contato: joao@horizonte.com.br, CNPJ 11.222.333/0001-81. "
    "Mais detalhes em https://intranet.acme.com.br/aurora."
)


class TestSanitizadorEmpresarial(unittest.TestCase):
    def test_mascara_tudo(self):
        s = SanitizadorEmpresarial(TERMOS)
        r = s.sanitizar(RELATORIO)
        for vazado in ("Acme", "Horizonte", "Aurora", "2.450.000", "joao@", "11.222.333", "intranet"):
            self.assertNotIn(vazado, r)

    def test_termo_mais_longo_primeiro(self):
        s = SanitizadorEmpresarial(TERMOS)
        r = s.sanitizar("Acme Brasil e Acme")
        self.assertEqual(r, "[EMPRESA_1] e [EMPRESA_2]")

    def test_case_insensitive_mesmo_token(self):
        s = SanitizadorEmpresarial(TERMOS)
        r = s.sanitizar("ACME BRASIL e acme brasil")
        self.assertEqual(r, "[EMPRESA_1] e [EMPRESA_1]")

    def test_valores_podem_ser_mantidos(self):
        s = SanitizadorEmpresarial(TERMOS, mascarar_valores=False)
        self.assertIn("R$ 2.450.000,00", s.sanitizar(RELATORIO))

    def test_restaurar(self):
        s = SanitizadorEmpresarial(TERMOS)
        limpo = s.sanitizar("Contrato de R$ 1.000,00 com Projeto Aurora")
        self.assertIn("R$ 1.000,00", s.restaurar(limpo))
        self.assertIn("Projeto Aurora", s.restaurar(limpo))

    def test_detector_extra_ner(self):
        ner = lambda texto: [("Carlos Menezes", "NOME")] if "Carlos Menezes" in texto else []
        s = SanitizadorEmpresarial(detectores_extras=[ner])
        self.assertEqual(s.sanitizar("Falou Carlos Menezes."), "Falou [NOME_1].")


class TestPipeline(unittest.TestCase):
    def test_llm_nunca_ve_dado_real(self):
        recebidos = []

        def llm(prompt):
            recebidos.append(prompt)
            return "Resumo: [EMPRESA_1] renovou com [CLIENTE_1] por [VALOR_1]."

        p = PipelineResumo(TERMOS)
        out = p.resumir(RELATORIO, llm, confirmar=lambda prep: True)
        enviado = "\n".join(recebidos)
        for vazado in ("Acme", "Horizonte", "2.450.000", "joao@", "11.222.333"):
            self.assertNotIn(vazado, enviado)
        # resposta final restaurada localmente
        self.assertIn("Acme Brasil", out)
        self.assertIn("R$ 2.450.000,00", out)

    def test_bloqueia_dado_sensivel(self):
        p = PipelineResumo(TERMOS)
        with self.assertRaises(ErroDeRisco):
            p.resumir("O funcionário apresentou atestado de depressão.", llm_simulado, lambda _: True)

    def test_sensivel_liberado_explicitamente(self):
        p = PipelineResumo(TERMOS)
        out = p.resumir("Houve atestado médico.", llm_simulado, lambda _: True, permitir_sensiveis=True)
        self.assertIsInstance(out, str)

    def test_alerta_sem_confirmacao_bloqueia(self):
        p = PipelineResumo(TERMOS)
        with self.assertRaises(ErroDeRisco):  # "Maria Souza" sobra -> alerta -> exige revisão
            p.resumir("A analista Maria Souza concluiu a auditoria.", llm_simulado)

    def test_usuario_cancela(self):
        p = PipelineResumo(TERMOS)
        with self.assertRaises(ErroDeRisco):
            p.resumir(RELATORIO, llm_simulado, confirmar=lambda prep: False)

    def test_texto_limpo_sem_alertas_passa_sem_confirmacao(self):
        p = PipelineResumo(TERMOS)
        out = p.resumir("As vendas cresceram em março.", lambda pr: "Vendas subiram.")
        self.assertEqual(out, "Vendas subiram.")

    def test_mapa_novo_por_documento(self):
        vistos = []
        p = PipelineResumo(TERMOS)
        for _ in range(2):
            p.resumir("Projeto Aurora.", lambda pr: vistos.append(pr) or "ok", lambda _: True)
        # nos dois envios o primeiro marcador reinicia em _1 (sem correlação entre documentos)
        self.assertTrue(all("[PROJETO_1]" in v for v in vistos))

    def test_marcador_inventado_gera_aviso(self):
        p = PipelineResumo(TERMOS)
        out = p.resumir("Projeto Aurora.", lambda pr: "Veja [EMPRESA_9].", lambda _: True)
        self.assertIn("AVISO", out)

    def test_map_reduce_texto_longo(self):
        chamadas = []
        p = PipelineResumo(TERMOS, limite_chars=200)
        texto = "\n\n".join(f"Parágrafo {i} sobre vendas e resultados do trimestre." * 3 for i in range(10))
        p.resumir(texto, lambda pr: chamadas.append(pr) or "parcial", lambda _: True)
        self.assertGreater(len(chamadas), 2)

    def test_auditoria_sem_dados_pessoais(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "aud.jsonl")
            p = PipelineResumo(TERMOS, auditoria_path=caminho)
            p.resumir(RELATORIO, llm_simulado, lambda _: True)
            conteudo = open(caminho, encoding="utf-8").read()
            for vazado in ("Acme", "Horizonte", "joao@", "2.450.000"):
                self.assertNotIn(vazado, conteudo)
            reg = json.loads(conteudo.splitlines()[0])
            self.assertEqual(reg["decisao"], "ENVIADO")
            self.assertEqual(len(reg["sha256_texto_enviado"]), 64)


TABELA = """| ID | Cliente | Valor | Status |
| -- | ------- | ----: | ------ |
| 1 | 001 | 250.00 | pago |
| 2 | 002 | 1250,50 | PAGO |
| 3 | 003 | 150 | pago |

Fim da tabela, 99,90 fora dela."""


class TestMelhoriasRelatorio(unittest.TestCase):
    def test_coluna_de_valor_em_tabela(self):
        r = SanitizadorEmpresarial().sanitizar(TABELA)
        for v in ("250.00", "1250,50", "| 150 |"):
            self.assertNotIn(v, r)
        self.assertIn("| 001 |", r)   # coluna Cliente intacta
        self.assertIn("pago", r)      # coluna Status intacta
        self.assertIn("99,90", r)     # texto fora da tabela não é tocado

    def test_camelcase_gera_alerta(self):
        _, nomes, _ = verificar_residuo("A NovaHorizonte entregou o projeto.")
        self.assertIn("NovaHorizonte", nomes)

    def test_alerta_nao_cruza_linhas(self):
        _, nomes, _ = verificar_residuo("Cidade: Teófilo Otoni\nEstado: MG")
        self.assertEqual(nomes, ["Teófilo Otoni"])

    def test_ignorar_alertas(self):
        p = PipelineResumo(ignorar_alertas=["Teófilo Otoni"])
        prep = p.preparar("Cidade: Teófilo Otoni")
        self.assertFalse(prep.tem_alertas)


class TestUtil(unittest.TestCase):
    def test_dividir(self):
        partes = dividir("a" * 150 + "\n\n" + "b" * 150, limite=200)
        self.assertEqual(len(partes), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
