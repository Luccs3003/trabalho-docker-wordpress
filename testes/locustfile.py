import json
import os
import time
from pathlib import Path

import gevent
from locust import FastHttpUser, between, events, task

cenario = os.environ.get('CENARIO', 'imagem-1mb')
dados = json.loads(Path('/dados/cenarios.json').read_text())[cenario]
ambiente = None
cpu_alta = False


@events.init.add_listener
def iniciar(environment, **kwargs):
    global ambiente
    ambiente = environment


@events.cpu_warning.add_listener
def registrar_cpu(environment, **kwargs):
    global cpu_alta
    cpu_alta = True


@events.spawning_complete.add_listener
def usuarios_prontos(user_count, **kwargs):
    if os.environ.get('SAIDA'):
        gevent.spawn(coletar, user_count)


def coletar(usuarios):
    aquecimento = int(os.environ['AQUECIMENTO'])
    duracao = int(os.environ['DURACAO'])
    gevent.sleep(aquecimento)
    ambiente.stats.reset_all()
    inicio = time.time()
    gevent.sleep(duracao)
    registro = dict(cenario=cenario, usuarios=usuarios, instancias=int(os.environ['INSTANCIAS']),
                    usuarios_finais=ambiente.runner.user_count, aquecimento_s=aquecimento,
                    duracao_s=duracao, duracao_real_s=time.time() - inicio, cpu_alta=cpu_alta)
    Path(os.environ['SAIDA'] + '_meta.json').write_text(json.dumps(registro))
    ambiente.runner.quit()


class Leitor(FastHttpUser):
    wait_time = between(1, 3)
    connection_timeout = 60
    network_timeout = 60
    # A conexao e com nginx; Host corresponde ao endereco cadastrado no WordPress.
    default_headers = {'Host': dados['host']}

    @task
    def ler_post(self):
        with self.client.get(dados['post'], name='post', allow_redirects=False,
                             catch_response=True) as resposta:
            if resposta.status_code != 200:
                resposta.failure(f'Post HTTP {resposta.status_code}')
            elif dados['imagem'] and dados['imagem'] not in resposta.text:
                resposta.failure('Imagem ausente no post')
            elif not dados['imagem'] and len(resposta.content) < dados['bytes']:
                resposta.failure('Texto menor que o esperado')
        # Locust nao baixa automaticamente imagens referenciadas pelo HTML.
        if dados['imagem']:
            with self.client.get(dados['imagem'], name='imagem', allow_redirects=False,
                                 catch_response=True) as resposta:
                if resposta.status_code != 200 or len(resposta.content) != dados['bytes']:
                    resposta.failure('Falha no download da imagem')
