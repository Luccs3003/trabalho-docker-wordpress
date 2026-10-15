# WordPress com Nginx e Docker Compose

Trabalho de Computação Distribuída.

Nginx funcionando como balanceador de carga para 3 instâncias do WordPress,
todas usando o mesmo banco MySQL.

## Como rodar

    docker compose up -d

Acessar http://localhost

## Testar o balanceamento

    curl -I http://localhost/

O header `X-Upstream` alterna entre os IPs dos 3 containers do WordPress.