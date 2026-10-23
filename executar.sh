#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# Impede que o Git Bash transforme caminhos dos conteineres em caminhos Windows.
export MSYS_NO_PATHCONV=1
pasta=coleta-50-200-500
usuarios=(50 200 500)
duracao=60
aquecimento=15
relatorio=0
piloto=0
conferir=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --relatorio) relatorio=1; shift ;;
        --conferir) conferir=1; shift ;;
        --piloto)
            valor=${2:-}
            [[ $valor =~ ^[1-9][0-9]{0,4}$ ]] || { echo 'Informe --piloto NUMERO (1 a 10000).' >&2; exit 1; }
            piloto=$2
            (( piloto <= 10000 )) || { echo 'O limite do piloto e 10000.' >&2; exit 1; }
            shift 2 ;;
        -h|--help)
            echo 'Uso: bash executar.sh [--relatorio] [--conferir | --piloto NUMERO]'
            exit 0 ;;
        *) echo "Opcao desconhecida: $1" >&2; exit 1 ;;
    esac
done
(( conferir == 0 || piloto == 0 )) || { echo 'Use --conferir ou --piloto, separadamente.' >&2; exit 1; }
if (( conferir )); then
    pasta=conferencia-bash; usuarios=(100); duracao=5; aquecimento=2
elif (( piloto )); then
    pasta="piloto-$piloto"; usuarios=("$piloto")
fi

anterior=${NGINX_CONFIG-}
processo=''
vigia=''
restaurar=1
iniciado=0
limpar() {
    local codigo=$?
    trap - EXIT INT TERM
    [[ -z $vigia ]] || { kill "$vigia" 2>/dev/null || true; wait "$vigia" 2>/dev/null || true; }
    if [[ -n $processo ]]; then
        kill "$processo" 2>/dev/null || true
        docker rm -f carga-wordpress || true
    fi
    if [[ -n $anterior ]]; then export NGINX_CONFIG=$anterior; else unset NGINX_CONFIG; fi
    if (( iniciado && restaurar )); then
        docker compose up -d --wait db wordpress1 wordpress2 wordpress3 &&
            docker compose up -d --no-deps --force-recreate nginx ||
            echo 'Nao foi possivel restaurar o site. Confira o Docker.' >&2
    fi
    exit "$codigo"
}
trap limpar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

arquitetura() {
    local n=$1 i cabecalhos enderecos=''
    docker compose stop nginx
    for i in 2 3; do
        if (( i > n )); then docker compose stop "wordpress$i"; fi
    done
    local servicos=(db)
    for ((i=1; i<=n; i++)); do servicos+=("wordpress$i"); done
    docker compose up -d --wait "${servicos[@]}"
    export NGINX_CONFIG="./.dados/nginx-$n.conf"
    docker compose up -d --no-deps --force-recreate nginx
    docker compose exec -T nginx nginx -t
    for i in 1 2 3 4 5 6; do
        cabecalhos=$(docker compose exec -T wordpress1 curl -fsSI --retry 3 \
            --retry-connrefused --max-time 30 http://nginx/)
        enderecos+="$cabecalhos"$'\n'
    done
    local quantidade
    quantidade=$(printf '%s' "$enderecos" | awk 'tolower($1)=="x-upstream:" {print $2}' | sort -u | wc -l)
    [[ $quantidade -eq $n ]] || { echo 'Confira o balanceamento do Nginx.' >&2; return 1; }
}

# Prazo externo independente do temporizador do Locust; funciona sem GNU timeout.
vigiar() {
    trap - EXIT
    local espera
    sleep "$1" & espera=$!
    trap 'kill "$espera" 2>/dev/null || true; exit 0' TERM INT
    wait "$espera"
    printf 'prazo excedido\n' > "$3"
    echo 'Coleta excedeu o prazo. Confira o Docker.' >&2
    kill "$2" 2>/dev/null || true
    docker rm -f carga-wordpress
}

mkdir -p ".dados/$pasta" resultados
case "$(uname -s)" in
    # Git Bash fornece um UID Windows que nao corresponde aos arquivos do Docker.
    MINGW*|MSYS*|CYGWIN*) usuario_docker=0:0 ;;
    *) usuario_docker="$(id -u):$(id -g)" ;;
esac
if (( ! relatorio )); then
    memoria=$(docker info --format '{{.MemTotal}}')
    case "$(uname -s)" in
        Darwin) sistema=macOS ;;
        MINGW*|MSYS*|CYGWIN*) sistema=Windows ;;
        *) sistema=Linux ;;
    esac
    # O Python e executado na imagem do Locust, inclusive para preparar o plano.
    docker compose run --rm -T --no-deps --user "$usuario_docker" --entrypoint python locust - \
        "$pasta" "$duracao" "$aquecimento" "$memoria" "$sistema" "${usuarios[@]}" <<'PY'
import json, sys
from pathlib import Path
pasta, duracao, aquecimento, memoria, sistema, *usuarios = sys.argv[1:]
plano = dict(duracao=int(duracao), aquecimento=int(aquecimento),
             memoria_bytes=int(memoria), sistema=sistema, plataforma_aplicacao='linux/amd64',
             usuarios=list(map(int, usuarios)))
arquivo = Path('/dados') / pasta / 'plano.json'
if arquivo.exists():
    salvo = json.loads(arquivo.read_text(encoding='utf-8-sig'))
    for chave in ['duracao', 'aquecimento', 'memoria_bytes', 'usuarios']:
        valor = salvo[chave]
        if chave == 'usuarios' and not isinstance(valor, list): valor = [valor]
        if valor != plano[chave]: raise SystemExit('Parametros diferentes: preserve e renomeie ' + str(arquivo.parent))
    if salvo.get('sistema', sistema) != sistema: raise SystemExit('Nao misture coletas de sistemas diferentes.')
else:
    arquivo.write_text(json.dumps(plano, indent=2))
print(f'Memoria disponivel ao Docker: {int(memoria) / 1024**3:.2f} GiB')
PY
    # Faz a substituicao apenas no bloco upstream, preservando nginx.conf.
    for n in 1 2 3; do
        servidores=''
        for ((i=1; i<=n; i++)); do servidores+="server wordpress$i; "; done
        awk -v servidores="$servidores" '
            /upstream wordpress[[:space:]]*\{/ { print "  upstream wordpress { " servidores "}"; bloco=1; next }
            bloco && /}/ { bloco=0; next }
            !bloco { print }
        ' nginx.conf > ".dados/nginx-$n.conf"
    done
    iniciado=1
    docker compose stop locust
    docker compose up -d --wait db wordpress1
    docker compose exec -T wordpress1 php /testes/preparar.php
    docker compose cp wordpress1:/var/www/html/wp-content/uploads/trabalho3/cenarios.json .dados/cenarios.json
    cp .dados/cenarios.json ".dados/$pasta/cenarios.json"
    passo=0
    total=$((9 * ${#usuarios[@]}))
    for n in 1 2 3; do
        arquitetura "$n"
        for cenario in imagem-1mb texto-400kb imagem-300kb; do
            for u in "${usuarios[@]}"; do
                passo=$((passo + 1))
                nome="$cenario-$n-$u"
                echo "[$passo/$total] $cenario | $n instancia(s) | $u usuarios"
                if [[ -f .dados/$pasta/$nome.ok && -f .dados/$pasta/${nome}_meta.json && -f .dados/$pasta/${nome}_stats.csv ]]; then
                    echo 'Ja concluido.'; continue
                fi
                rm -f ".dados/$pasta/${nome}_meta.json" ".dados/$pasta/$nome.ok" ".dados/$pasta/$nome.timeout"
                saida="/dados/$pasta/$nome"
                limite=$(((u + 49) / 50 + aquecimento + duracao + 240))
                docker compose run --rm -T --no-deps --user "$usuario_docker" --name carga-wordpress \
                    -e "CENARIO=$cenario" -e "INSTANCIAS=$n" -e "SAIDA=$saida" \
                    -e "AQUECIMENTO=$aquecimento" -e "DURACAO=$duracao" locust \
                    -f /testes/locustfile.py --host http://nginx --headless --only-summary \
                    -u "$u" -r 50 -t "${limite}s" --csv "$saida" --logfile "$saida.log" --exit-code-on-error 0 &
                processo=$!
                vigiar "$((limite + 30))" "$processo" ".dados/$pasta/$nome.timeout" & vigia=$!
                codigo=0
                wait "$processo" || codigo=$?
                kill "$vigia" 2>/dev/null || true
                wait "$vigia" 2>/dev/null || true
                vigia=''
                if (( codigo != 0 )); then
                    if [[ -f .dados/$pasta/$nome.timeout ]]; then restaurar=0; fi
                    exit "$codigo"
                fi
                processo=''
                [[ -f .dados/$pasta/${nome}_meta.json ]] || { echo "Execucao incompleta: $nome" >&2; exit 1; }
                printf 'concluido\n' > ".dados/$pasta/$nome.ok"
            done
        done
    done
fi

destino=/resultados
if (( piloto || conferir )); then destino="/dados/$pasta/resultado"; fi
docker compose run --rm -T --no-deps --user "$usuario_docker" --entrypoint python locust \
    /testes/relatorio.py "/dados/$pasta" "$destino"
if (( piloto || conferir )); then
    echo "Relatorio de verificacao: .dados/$pasta/resultado/relatorio.html. Entrega preservada."
else
    echo 'Abra resultados/relatorio.html. Os graficos e o CSV estao na mesma pasta.'
fi
