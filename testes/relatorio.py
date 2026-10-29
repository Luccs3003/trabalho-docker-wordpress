"""Le os CSVs do Locust e gera o resumo, seis graficos SVG e o relatorio HTML."""
import csv
import html
import json
import math
import re
import sys
from pathlib import Path

CENARIOS = {'imagem-1mb': 'Imagem de 1 MB', 'texto-400kb': 'Texto de 400 KB',
            'imagem-300kb': 'Imagem de 300 KB'}
USUARIOS = [50, 200, 500]
CORES = ['#4878a8', '#d89a43', '#69a16c']


def ler_resultados(pasta):
    linhas = []
    for arquivo in sorted(pasta.glob('*.ok')):
        nome = arquivo.stem
        meta = json.loads((pasta / f'{nome}_meta.json').read_text())
        with (pasta / f'{nome}_stats.csv').open(encoding='utf-8-sig', newline='') as entrada:
            estatisticas = {r['Name']: r for r in csv.DictReader(entrada)}
        post = estatisticas.get('post')
        total = estatisticas.get('Aggregated')
        if not post or not total or not int(post['Request Count']):
            continue
        if meta['usuarios_finais'] != meta['usuarios']:
            continue
        quantidade = int(total['Request Count'])
        falhas = int(total['Failure Count'])
        rps = float(total['Requests/s'])
        linhas.append(dict(cenario=meta['cenario'], instancias=meta['instancias'], usuarios=meta['usuarios'],
            media_ms=float(post['Average Response Time']), p95_ms=float(post['95%']),
            rps=rps, rps_sucesso=rps * (quantidade - falhas) / quantidade,
            falhas_percentual=100 * falhas / quantidade,
            requisicoes=quantidade, falhas=falhas, cpu_alta=meta['cpu_alta'],
            coleta_s=meta['duracao_s'], coleta_real_s=meta['duracao_real_s'],
            intervalo_csv_s=quantidade / rps if rps else 0))
    linhas.sort(key=lambda r: (r['cenario'], r['instancias'], r['usuarios']))
    return linhas


def grafico(cenario, dados, metrica):
    percentil = metrica == 'p95_ms'
    xs, series = (USUARIOS, [1, 2, 3]) if percentil else ([1, 2, 3], USUARIOS)
    titulo = CENARIOS[cenario] + (' — p95 do tempo de resposta' if percentil else ' — vazão')
    eixo_x = 'Usuários simultâneos' if percentil else 'Instâncias WordPress'
    eixo_y = 'p95 do HTML (ms)' if percentil else 'Requisições HTTP/s'
    valores = [r[metrica] for r in dados.values() if r['cenario'] == cenario]
    alvo = max(1, max(valores, default=1) / 5)
    ordem = 10 ** math.floor(math.log10(alvo))
    passo = next(n * ordem for n in [1, 2, 5, 10] if n * ordem >= alvo)
    teto = passo * 5
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 390" role="img">',
              f'<title>{html.escape(titulo)}</title>', '<rect width="760" height="390" fill="white"/>',
              '<g font-family="sans-serif" font-size="13" fill="#222">',
              f'<text x="380" y="24" text-anchor="middle" font-size="17">{html.escape(titulo)}</text>']
    for i, serie in enumerate(series):
        x = 110 + i * 205
        rotulo = f'{serie} ' + ('instância(s)' if percentil else 'usuários')
        partes += [f'<rect x="{x}" y="40" width="14" height="14" fill="{CORES[i]}"/>',
                   f'<text x="{x + 21}" y="52">{rotulo}</text>']
    for i in range(6):
        y = 300 - i * 44
        partes += [f'<line x1="90" y1="{y}" x2="720" y2="{y}" stroke="#ddd"/>',
                   f'<text x="80" y="{y+4}" text-anchor="end">{i * passo:g}</text>']
    for i, x in enumerate(xs):
        centro = 195 + i * 210
        partes.append(f'<text x="{centro}" y="325" text-anchor="middle">{x}</text>')
        for j, serie in enumerate(series):
            chave = (cenario, serie, x) if percentil else (cenario, x, serie)
            if chave not in dados:
                continue
            valor = dados[chave][metrica]
            altura = valor / teto * 220
            partes.append(f'<rect x="{centro - 54 + j*36}" y="{300-altura:.2f}" '
                          f'width="34" height="{altura:.2f}" fill="{CORES[j]}">'
                          f'<title>{valor:.2f}</title></rect>')
    partes += [f'<text x="400" y="365" text-anchor="middle">{eixo_x}</text>',
               f'<text transform="translate(20,190) rotate(-90)" text-anchor="middle">{eixo_y}</text>',
               '</g></svg>']
    return ''.join(partes)


def gerar_analise(dados):
    observacoes = []
    for cenario, titulo in CENARIOS.items():
        menor, maior = min(USUARIOS), max(USUARIOS)
        a, b = dados.get((cenario, 3, menor)), dados.get((cenario, 3, maior))
        if a and b and menor != maior:
            texto = (f'{titulo}: com três instâncias, ao passar de {menor} para {maior} usuários '
                     f'o p95 do HTML passou de {a["p95_ms"]:.0f} para {b["p95_ms"]:.0f} ms. ')
            uma, tres = dados.get((cenario, 1, maior)), dados.get((cenario, 3, maior))
            if uma and tres:
                texto += (f'Com {maior} usuários, a vazão foi de {uma["rps"]:.2f} req/s com uma instância '
                          f'e {tres["rps"]:.2f} req/s com três, mostrando que adicionar instâncias '
                          'não produziu crescimento proporcional neste ambiente.')
            observacoes.append(texto)
    return ''.join(f'<li>{o}</li>' for o in observacoes) or '<li>Faltam combinações para comparar as cargas e arquiteturas.</li>'


def gerar(pasta, destino):
    global USUARIOS
    plano = json.loads((pasta / 'plano.json').read_text(encoding='utf-8-sig'))
    valores = plano['usuarios']
    USUARIOS = sorted(valores if isinstance(valores, list) else [valores])
    esperado = 9 * len(USUARIOS)
    piloto = len(USUARIOS) < 3
    destino.mkdir(parents=True, exist_ok=True)
    linhas = ler_resultados(pasta)
    campos = ['cenario', 'instancias', 'usuarios', 'media_ms', 'p95_ms', 'rps', 'rps_sucesso',
              'falhas_percentual', 'requisicoes', 'falhas', 'cpu_alta', 'coleta_s', 'coleta_real_s', 'intervalo_csv_s']
    with (destino / 'resumo.csv').open('w', encoding='utf-8', newline='') as saida:
        escritor = csv.DictWriter(saida, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)
    dados = {(r['cenario'], r['instancias'], r['usuarios']): r for r in linhas}
    maior_carga = max(USUARIOS)
    carga_alta = [r for r in linhas if r['usuarios'] == maior_carga]
    falhas_carga_alta = sum(r['falhas'] > 0 for r in carga_alta)
    alertas_carga_alta = sum(r['cpu_alta'] for r in carga_alta)
    avaliacao = ''
    if carga_alta and falhas_carga_alta:
        avaliacao = (f'<p><strong>Atenção à carga de {maior_carga} usuários:</strong> '
            f'{falhas_carga_alta} de {len(carga_alta)} execuções tiveram falhas e '
            f'{alertas_carga_alta} registraram alerta de CPU do Locust. '
            'A redução da carga não garantiu estabilidade; os resultados ainda mostram '
            'saturação e não devem ser apresentados como três níveis livres de estouros.</p>')
    elif carga_alta and alertas_carga_alta:
        avaliacao = (f'<p>Não houve falhas de requisição na carga de {maior_carga} usuários. '
            f'Entretanto, houve alerta de CPU do Locust em {alertas_carga_alta} de {len(carga_alta)} execuções. '
            'Esse alerta é uma ressalva sobre a capacidade do gerador, '
            'não uma falha HTTP; as medições afetadas devem ser interpretadas com cautela.</p>')
    if len(dados) == esperado and not any(r['falhas'] for r in linhas):
        avaliacao = f'<p><strong>As {esperado} combinações terminaram sem falhas de requisição.</strong></p>' + avaliacao
    cenarios = json.loads((pasta / 'cenarios.json').read_text())
    tabela, figuras = [], []
    for cenario, titulo in CENARIOS.items():
        for n in [1, 2, 3]:
            for u in USUARIOS:
                r = dados.get((cenario, n, u))
                inicio = f'<td>{titulo}</td><td>{n}</td><td>{u}</td>'
                if r:
                    alerta = 'CPU Locust' if r['cpu_alta'] else '—'
                    if r['coleta_real_s'] > r['coleta_s'] * 1.2: alerta += ' / coleta atrasada'
                    if r['intervalo_csv_s'] > r['coleta_real_s'] * 1.2: alerta += ' / encerramento lento'
                    tabela.append('<tr>' + inicio + f'<td>{r["media_ms"]:.2f}</td><td>{r["p95_ms"]:.2f}</td>'
                        f'<td>{r["rps"]:.2f}</td><td>{r["falhas_percentual"]:.2f}%</td><td>{alerta}</td></tr>')
                else:
                    tabela.append('<tr>' + inicio + '<td colspan="5">Não coletado</td></tr>')
        for metrica, sufixo in [('p95_ms', 'tempo'), ('rps', 'vazao')]:
            svg = grafico(cenario, dados, metrica)
            (destino / f'{cenario}-{sufixo}.svg').write_text(svg, encoding='utf-8')
            figuras.append(svg)
    tamanhos = '; '.join(CENARIOS[c] + ': ' + f'{cenarios[c]["bytes"]:,}'.replace(',', '.') + ' bytes'
                         for c in CENARIOS)
    situacao = 'Coleta completa' if len(dados) == esperado else 'Coleta parcial'
    if piloto: situacao = 'Piloto de capacidade — ' + situacao.lower()
    cargas = ', '.join(f'{u:,}'.replace(',', '.') for u in USUARIOS)
    ambiente = ('Sistema hospedeiro: ' + html.escape(plano['sistema']) + '. '
                if plano.get('sistema') else 'Máquina com 8 GB de RAM; WSL configurado com limite de 4 GB. ')
    if plano.get('plataforma_aplicacao'):
        ambiente += 'Plataforma das imagens da aplicação: ' + html.escape(plano['plataforma_aplicacao']) + '. '
    historico = []
    for carga, origem in [(800, 'coleta-100-500-800'), (1200, 'piloto-1200'), (1500, 'coleta')]:
        arquivo_historico = pasta.parent / origem
        if arquivo_historico.exists():
            anteriores = [r for r in ler_resultados(arquivo_historico) if r['usuarios'] == carga]
            afetadas = [r for r in anteriores if r['falhas'] > 0]
            if afetadas:
                rotulo = f'{carga:,}'.replace(',', '.')
                historico.append(f'{rotulo} usuários: falhas em {len(afetadas)} de {len(anteriores)} '
                    f'execuções, de {min(r["falhas_percentual"] for r in afetadas):.2f}% a '
                    f'{max(r["falhas_percentual"] for r in afetadas):.2f}% nas execuções afetadas. '
                    f'Alerta de CPU do Locust em {sum(r["cpu_alta"] for r in anteriores)} execuções.')
    ensaios = ''
    if not piloto and USUARIOS == [50, 200, 500] and (historico or not plano.get('sistema')):
        ensaios = ('<h2>Ensaios anteriores com cargas maiores</h2>'
            '<p>Também foram testados 800, 1.200 e 1.500 usuários na mesma máquina com limite de 4 GB. '
            'Essas cargas provocaram estouros: erros HTTP, falhas de conexão/download, encerramentos '
            'lentos e alertas de CPU do gerador. Por isso, a matriz principal foi refeita com '
            '50, 200 e 500 usuários. As cargas maiores não estão misturadas nos gráficos desta matriz.</p>'
            '<ul>' + ''.join(f'<li>{h}</li>' for h in historico) + '</ul>')
    analise = gerar_analise(dados)
    pagina = f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trabalho 3 — Resultados</title>
<style>body{{font:16px/1.5 sans-serif;max-width:1100px;margin:35px auto;padding:0 18px;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border:1px solid #ccc;padding:7px;text-align:right}}
td:first-child,th:first-child{{text-align:left}}th{{background:#eee}}.tabela{{overflow-x:auto}}
.graficos{{display:grid;grid-template-columns:1fr 1fr;gap:15px}}svg{{width:100%;height:auto}}
@media(max-width:750px){{.graficos{{display:block}}}}@media print{{svg{{break-inside:avoid}}}}</style>
<h1>Trabalho 3 — Testes de carga do WordPress</h1>
<p>Daniel Enrique (2323216), Lucas Cardoso (2218942) e Pedro Luis (2315086).</p>
<h2>Condições do teste</h2>
<p><strong>{situacao}: {len(dados)}/{esperado} combinações.</strong> Usuários: {cargas}.
Instâncias WordPress: 1, 2 e 3. {html.escape(tamanhos)}.</p>
<p>{ambiente.rstrip()}
O Docker informou {plano['memoria_bytes']/1024**3:.2f} GiB disponíveis nesta coleta.
Locust 2.32.6, entrada de 50 usuários/s, aquecimento de {plano['aquecimento']} s após a rampa
e coleta de {plano['duracao']} s. Os usuários esperam de 1 a 3 s entre visitas.</p>
<p>O Locust acessa o Nginx. Cada visita busca o HTML e a imagem original quando presente;
CSS, JavaScript e outros recursos do tema não são carregados. As três instâncias usam
o mesmo banco e limite de 20 processos Apache por instância. Os JPEGs são gerados com
ruído determinístico e qualidade ajustada ao tamanho, sem padding ou miniaturas.</p>
{ensaios}
<h2>Resultados</h2>
<p>Média e p95 medem o HTML do post em ms. RPS soma HTML e imagem quando houver, inclui falhas e não
representa visitas/s. Falhas são agregadas. As estatísticas são zeradas após o aquecimento;
requisições iniciadas antes dele podem concluir na janela e requisições pendentes são
interrompidas no encerramento. As métricas vêm do CSV final do Locust: em encerramentos lentos,
as estatísticas podem incluir conclusões de requisições após a janela solicitada.
O resumo registra o tempo solicitado, o tempo medido até iniciar o encerramento e
o intervalo equivalente do CSV (quantidade/RPS). Dados ausentes não são zeros.</p>
{avaliacao}
<div class="tabela"><table><tr><th>Cenário</th><th>Instâncias</th><th>Usuários</th><th>Média (ms)</th>
<th>p95 (ms)</th><th>RPS</th><th>Falhas</th><th>Alertas</th></tr>{''.join(tabela)}</table></div>
<h2>Gráficos</h2><p>p95 do HTML por número de usuários e vazão por número de instâncias, para cada conteúdo.</p>
<div class="graficos">{''.join(figuras)}</div>
<h2>Análise</h2><ul>{analise}</ul>
<p>Latência maior sem crescimento proporcional de vazão é compatível com saturação.
WordPress, MySQL e Locust compartilham a máquina: mais contêineres não significam mais
hardware. Alertas de CPU do Locust indicam que o gerador também pode limitar o teste;
falhas e janelas atrasadas devem ser consideradas ao interpretar os gráficos.</p>
<p>RPS elevado com muitas falhas não demonstra maior capacidade de servir o conteúdo.
A coluna rps_sucesso do resumo desconta as falhas da taxa agregada. Trata-se de uma
execução por combinação, sem repetições para estimar a variabilidade; os resultados
descrevem este ambiente compartilhado e não isolam o ganho de escalabilidade dos servidores.</p>
<p>{'Este piloto testa uma única carga e não substitui a matriz final de três cargas.' if piloto else
('Todas as combinações foram coletadas.' if len(dados) == esperado else 'Ainda faltam combinações para concluir a atividade.')}
Os números utilizados estão em <a href="resumo.csv">resumo.csv</a>.
Este HTML contém os seis gráficos e pode ser aberto offline.</p></html>'''
    (destino / 'relatorio.html').write_text(pagina, encoding='utf-8')
    print(f'{len(dados)}/{esperado} combinações; relatório e gráficos em {destino}')


def gerar_graficos_csv(arquivo, destino):
    """Regenera os gráficos e os substitui no HTML usando somente o resumo CSV."""
    global USUARIOS
    with arquivo.open(encoding='utf-8-sig', newline='') as entrada:
        linhas = []
        for linha in csv.DictReader(entrada):
            linhas.append(dict(cenario=linha['cenario'], instancias=int(linha['instancias']),
                usuarios=int(linha['usuarios']), p95_ms=float(linha['p95_ms']),
                rps=float(linha['rps'])))
    USUARIOS = sorted({r['usuarios'] for r in linhas})
    dados = {(r['cenario'], r['instancias'], r['usuarios']): r for r in linhas}
    graficos = []
    for cenario in CENARIOS:
        for metrica, sufixo in [('p95_ms', 'tempo'), ('rps', 'vazao')]:
            svg = grafico(cenario, dados, metrica)
            (destino / f'{cenario}-{sufixo}.svg').write_text(svg, encoding='utf-8')
            graficos.append(svg)
    relatorio = destino / 'relatorio.html'
    pagina = relatorio.read_text(encoding='utf-8')
    pagina, quantidade = re.subn(r'<svg\b.*?</svg>', lambda _: graficos.pop(0), pagina,
                                 count=6, flags=re.DOTALL)
    if quantidade != 6:
        raise SystemExit(f'Esperados 6 gráficos no relatório, encontrados {quantidade}.')
    pagina = pagina.replace('Tempo por número de usuários e vazão por número de instâncias',
                            'p95 do HTML por número de usuários e vazão por número de instâncias')
    pagina, quantidade_analise = re.subn(r'(<h2>Análise</h2><ul>).*?(</ul>)',
        lambda m: m.group(1) + gerar_analise(dados) + m.group(2), pagina,
        count=1, flags=re.DOTALL)
    if quantidade_analise != 1:
        raise SystemExit('Seção de análise não encontrada no relatório.')
    relatorio.write_text(pagina, encoding='utf-8')
    print(f'6 gráficos regenerados a partir de {arquivo}')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--csv':
        gerar_graficos_csv(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        gerar(Path(sys.argv[1]), Path(sys.argv[2]))
