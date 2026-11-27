# BFTracker

Monitor de preços, cupons e ofertas relâmpago para lojas brasileiras, pensado para rodar no
seu próprio VPS com Docker Compose. Avisa por **push**, **e-mail** e **WhatsApp**.

## O que ele faz

- **Monitora produtos** por nome (ex.: `PS5`) ou por link, de 5 em 5 minutos até 1 vez por dia.
- **Agrupa variantes** (Pro, Digital, com leitor, armazenamento, pacotes com jogos) e avisa
  quando surge variante nova, oferta nova, queda de preço, preço-alvo, menor preço já visto,
  volta ao estoque, cupom no anúncio ou cupom que pode servir na loja mais barata.
- **Diz onde comprar:** melhor preço em loja confiável, melhor parcelamento sem juros e a oferta
  mais barata de todas, com alerta quando a loja pede cuidado.
- **Desmascara falso desconto** comparando com o histórico (próprio e importado de comparadores).
- **Usados e recondicionados** com filtro por estado e cidade/região e aviso de oportunidade.
- **Radar ao vivo** de sites de tecnologia, fóruns e canais de promoção, com filtros de
  relâmpago, cupom, Black Friday e possível bug de preço.
- **Interesses:** receba avisos por categoria, loja, palavra-chave, preço máximo ou desconto.
- Interface responsiva (tema claro/escuro), instalável no celular como aplicativo (PWA).
- Acesso restrito por usuário e senha; vários usuários, com dados separados.

## Subindo no Dokploy + Cloudflare (com Push Notification)

O `docker-compose.yml` já está estruturado nativamente para o **Dokploy** (sem Caddy nem portas
80/443 disputando com o Traefik do Dokploy, com rede interna isolada para o Postgres/worker e
`dokploy-network` apenas no serviço `app` na porta `8000`).

### 1. Cloudflare (DNS e SSL)

1. Na Cloudflare, crie um registro **A** (ex.: `ofertas.seudominio.com`) apontando para o IP do
   seu servidor Dokploy, com **Proxy ativado (nuvem laranja)**.
2. Em **SSL/TLS → Visão geral**, use o modo **Completo (`Full`)** ou **Completo (estrito / `Full strict`)**
   — **nunca use `Flexível`**, pois gera loop infinito de redirecionamento HTTPS com o Traefik.
3. Em **Speed → Optimization**, mantenha o **Rocket Loader** desligado (o BFTracker já marca seus
   scripts com `data-cfasync="false"` e envia `CDN-Cache-Control: no-store` em `/sw.js`,
   `/manifest.webmanifest` e `/api/*` para que a Cloudflare nunca sirva Service Worker vencido).

### 2. Criar o serviço no Dokploy

1. No Dokploy, crie um serviço do tipo **Compose** (`Docker Compose`) apontando para este
   repositório (`Compose Path`: `./docker-compose.yml`).
2. Na aba **Environment** do serviço no Dokploy, preencha (você pode rodar
   `./scripts/setup.sh ofertas.seudominio.com voce@exemplo.com` localmente para gerar senhas
   aleatórias prontas):

   ```env
   POSTGRES_PASSWORD=gere-uma-senha-forte-de-32-caracteres
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=sua-senha-inicial-forte
   ADMIN_EMAIL=voce@exemplo.com
   SECRET_KEY=gere-uma-chave-aleatoria-de-48-caracteres
   PUBLIC_URL=https://ofertas.seudominio.com
   TIMEZONE=America/Sao_Paulo
   ```

3. Na aba **Domains** do serviço Compose no Dokploy, clique em **Add Domain**:
   - **Service Name:** `app`
   - **Container Port:** `8000`
   - **Host:** `ofertas.seudominio.com`
   - **HTTPS:** ativado (**Let's Encrypt**)
4. Clique em **Deploy**. Acesse `https://ofertas.seudominio.com`, entre com `admin` e ative o
   **Push** no celular e no computador!

## Configurando os avisos

Tudo pode ser configurado em **Configurações → Integrações** (segredos ficam cifrados no banco)
ou pelo `.env`.

### Push no celular

1. Abra o BFTracker no celular por HTTPS.
2. **iPhone/iPad:** Compartilhar → *Adicionar à Tela de Início* e abra pelo ícone (iOS 16.4+).
3. Toque em **Ativar push** e depois em **Testar**.

As chaves VAPID são geradas automaticamente no primeiro início.

Em 25/11/2026 o envio foi validado de ponta a ponta no Chrome para macOS (aplicativo → serviço
de push do Google → notificação no navegador). Android e iPhone ainda não foram testados em
aparelho.

### E-mail

Informe servidor, porta, usuário, senha e remetente SMTP. No Gmail use `smtp.gmail.com`,
porta `587`, STARTTLS e uma [senha de app](https://support.google.com/accounts/answer/185833).
Alguns provedores de VPS bloqueiam a porta 25; prefira 587 ou 465. Cada usuário informa o
próprio e-mail em *Minha conta*.

### WhatsApp

Escolha um provedor:

| Provedor | Quando usar |
| --- | --- |
| **WAHA** | Servidor próprio, pareado com um número seu por QR Code |
| **Evolution API** | Você já tem uma instância |
| **Meta Cloud API** | Opção oficial; exige conta Business e modelo aprovado |
| **CallMeBot** | Gratuito para uso pessoal; cada usuário gera a própria chave |
| **Webhook** | Para n8n, Zapier e afins |

Com WAHA:

```bash
docker compose --profile whatsapp up -d
```

No `.env`, use `WHATSAPP_PROVIDER=waha` (ou escolha na interface) e, em servidores ARM,
`WAHA_IMAGE=devlikeapro/waha:arm`. Depois vá em **Configurações → Integrações → Conectar
WhatsApp** e leia o QR Code.

> WAHA e Evolution usam o WhatsApp de forma não oficial: há risco de o número ser bloqueado.
> Prefira um número secundário, ou a API oficial da Meta.

### X (Twitter) — Monitoramento dos produtos cadastrados

O BFTracker acompanha ofertas publicadas no X para cada produto ativo em **Monitorados**:

1. **Automático via API oficial do X v2:** em **Configurações → Integrações → X (Twitter)** (ou no
   `.env`), informe o `X_BEARER_TOKEN` (ou `X_API_KEY` + `X_API_SECRET`, trocados automaticamente
   por Bearer Token). Os produtos monitorados são agrupados em lotes econômicos de até 512
   caracteres e consultados com `since_id` para não repetir leituras. Também acompanha perfis de
   promoção (`X_ACCOUNTS`, como `@pelandobr`, `@promobitoficial`, `@pechinchou`, `@nerdofertas`).
2. **Automático via ponte RSS (`X_RSS_SEARCH_URL`):** opcional, compatível com RSSHub, RSS-Bridge
   ou geradores de RSS que aceitem `{query}`.
3. **Pelo navegador (sem precisar de chave da API do X):** cada monitorado (e a lista geral em
   **Monitorados**) traz o botão **🐦 X ao vivo** com a busca pronta na aba *Latest* (`f=live`), e
   a **Extensão BFTracker Companion** captura os tweets de oferta automaticamente enquanto você
   rola a página.

### Mercado Livre (sem precisar da API oficial), OLX e hardMOB

Como o Mercado Livre exige aprovação de até 10 dias na API oficial e OLX/hardMOB bloqueiam clientes
automatizados, o BFTracker combina **4 camadas legítimas** para você não perder nada:

1. **Comunidades e radar integrados aos Monitorados (24h, automático, já ativo):**
   - **Gatry** (busca por produto e feed contínuo na API pública `/v1/`), **Pelando** (ofertas
     recentes, mais quentes e páginas de cupons ativos do Mercado Livre, Amazon, Magalu, Shopee e
     AliExpress), **Promobit** (incluindo KaBuM!, Mercado Livre, Magalu, Amazon, Casas Bahia) e
     **18 canais públicos do Telegram** (incluindo `hardmob_promo`,
     `boletando`, `linksbrazil`, `pelandobr`, `benchpromos` etc.).
   - **Ponte Radar → Monitorados:** toda oferta com preço colhida no radar ou no X que bater com
     um produto seu entra automaticamente como oferta dentro do monitorado, atualizando o melhor
     preço, o histórico diário e disparando avisos de meta/relâmpago.
2. **Alertas oficiais por E-mail via IMAP (24h, automático, opcional):**
   - Em **Configurações → Integrações → Alertas por E-mail via IMAP**, informe servidor SSL (ex.:
     `imap.gmail.com`, porta `993` e senha de app). O leitor abre a caixa em modo **somente
     leitura (`BODY.PEEK[]`)** — nunca marca seus e-mails pessoais como lidos — e importa na hora:
     - **OLX:** novos anúncios das suas [buscas salvas](https://ajuda.olx.com.br/s/article/favoritos-buscas-anuncios) na sua região;
     - **hardMOB:** novos tópicos da assinatura instantânea por e-mail do fórum *Promoções*;
     - **Google Alerts** e avisos do **Mercado Livre**.
3. **Busca Web / Shopping opcional (`SERPER_API_KEY` ou `BRAVE_API_KEY`):**
   - Usa a API oficial do Serper.dev (Google Shopping Brasil + busca web, com cota gratuita
     imediata no cadastro) ou Brave Search para consultar ofertas do **Mercado Livre**, **OLX**
     (filtrada pelo seu estado/região), **Magalu**, **Casas Bahia** e **Shopee** diretamente.
4. **Extensão do navegador — BFTracker Companion (Manifest V3) + Favorito:**
   - Em **Extensão e captura** (`/importar`), baixe `bftracker-companion.zip`, carregue em
     `chrome://extensions` e gere uma chave pessoal (`bft_...`).
   - Enquanto você navega no **Mercado Livre** (buscas de novos/usados, `/ofertas`, `/cupons` e
     páginas de produto, com leitura de preço à vista, parcelamento sem juros, frete grátis e
     cupom), **OLX**, **hardMOB Promoções**, **X (Twitter)** ou **Enjoei**, a extensão envia os
     itens automaticamente para o seu BFTracker, sem janelas de confirmação e sem nunca acessar
     senhas ou cookies. No celular, o favorito *Enviar ao BFTracker* faz o mesmo sob demanda.

### Mercado Livre (API oficial, opcional)

Se você já tiver aplicativo aprovado em [developers.mercadolivre.com.br](https://developers.mercadolivre.com.br):
cadastre a URI `https://SEU-DOMINIO/api/admin/ml/callback` (com `offline_access` e PKCE
desativado), salve `Client ID` e `Client Secret` em **Configurações → Integrações** e clique em
**Conectar Mercado Livre**. **Não é obrigatória.**

## Fontes de ofertas

| Grupo | Fontes |
| --- | --- |
| Comparadores e comunidades pesquisáveis por produto | Zoom, Buscapé, Gatry (`/v1/`), Busca Web / Shopping opcional (Serper / Brave) |
| Lojas consultadas diretamente | Amazon, KaBuM!, Americanas, Samsung, Motorola, Electrolux, Brastemp, Compra Certa, Sam's Club, Webcontinental, Casa & Video |
| Usados e recondicionados | Trocafone, OLX (alertas IMAP, Busca Web, Extensão Companion e coletor direto), Enjoei (Extensão/Favorito), Mercado Livre usados, itens usados da Amazon e KaBuM! |
| X (Twitter) | Busca automática por produtos monitorados (`x:watches`), perfis de promoção (`x:accounts`), ponte RSS (`X_RSS_SEARCH_URL`) e Extensão Companion |
| Radar: comunidades e portais | Pelando (recentes, mais quentes, categorias e cupons por loja), Gatry (promoções e cupons), Promobit (ofertas e cupons por loja), hardMOB (assinatura IMAP, Extensão Companion e canal espelho) |
| Radar: sites (RSS) | TudoCelular, Canaltech, Tecnoblog, Adrenaline, Mundo Conectado, MeuPlayStation, MacMagazine, TecMundo, Olhar Digital |
| Radar: canais públicos do Telegram | Pelando, Pechinchou, Nerd Ofertas, Achados do Tecnoblog, TudoCelular, Baita Compra Tech, Ofertas Adrenaline, Bench Promos, Seletronic, PromoTop, PC do Fafa, KaBuM!, Boletando, Ofertas PC Gamer & Hardware, LinksBR, Xet das Promoções, MacMagazine, hardMOB Promo |
| Alertas por e-mail (IMAP opcional) | OLX (buscas salvas), hardMOB (fórum Promoções), Mercado Livre, Google Alerts, Pelando, Promobit e X |
| Qualquer loja | Monitoramento por link (dados schema.org/Open Graph) e Extensão BFTracker Companion |

Você pode acrescentar canais do Telegram, feeds RSS (inclusive RSS do Google Alerts) e lojas VTEX
em **Configurações → Fontes**.

### Diagnóstico de fontes no servidor

Teste no seu servidor quais fontes respondem:

```bash
docker compose exec app python -m app.cli check-sources ps5
```

O BFTracker se identifica honestamente no `User-Agent`, limita a frequência por domínio, recua
quando um site bloqueia (como HTTP 403/503 na OLX, Amazon ou hardMOB direto) e **nunca contorna
CAPTCHA nem proteções anti-robô**. Fontes opcionais sem chave aparecem como `OPCIONAL (não
configurada)` até que você preencha em **Configurações → Integrações**. Use para fins pessoais e
respeite os termos de cada serviço; qualquer fonte pode ser desligada em **Configurações →
Fontes**.

## Lojas e confiança

Retrato levantado em 25/11/2026 nas páginas públicas do Reclame Aqui; reputação muda, confira.

| Loja | Situação na consulta |
| --- | --- |
| [Amazon](https://www.reclameaqui.com.br/empresa/amazon/) | Ótima (8,0) |
| [Magazine Luiza](https://www.reclameaqui.com.br/empresa/magazine-luiza-loja-online/) | Ótima (8,2) |
| [KaBuM!](https://www.reclameaqui.com.br/empresa/kabum/) | Ótima (8,0) |
| [Fast Shop](https://www.reclameaqui.com.br/empresa/fast-shop/) | Ótima (8,2) |
| Mercado Livre | Boa (7,6) |
| [Casas Bahia](https://www.reclameaqui.com.br/empresa/casas-bahia-loja-online/) | Ruim (5,9): o app marca como "atenção" |

As demais classificações do aplicativo (lojas de fabricantes, outros varejistas) são avaliação
editorial. A lista completa está em [`backend/app/core/stores.py`](backend/app/core/stores.py).
Antes de comprar em loja desconhecida, consulte a lista "Evite esses sites" do
[Procon-SP](https://www.procon.sp.gov.br/).

## Operação

```bash
docker compose logs -f app worker
```

Atualizar:

```bash
git pull && docker compose up -d --build
```

Backup do banco e do `.env` (contém segredos):

```bash
./scripts/backup.sh
```

Esqueceu a senha:

```bash
docker compose exec app python -m app.cli reset-password admin
```

Guarde o `SECRET_KEY`: se mudar, os segredos salvos pela interface precisam ser digitados de
novo. A versão atual cria as tabelas automaticamente, mas não migra um banco existente se o
esquema mudar numa versão futura.

## Segurança

- Senhas com Argon2; sessão em cookie `HttpOnly`, `SameSite=Lax` e `Secure` sob HTTPS.
- Limite de tentativas de login, proteção CSRF, CSP restritiva e sem documentação pública da API.
- URLs informadas por usuários não podem apontar para a rede interna (proteção contra SSRF).
- Segredos cadastrados pela interface ficam cifrados e nunca voltam para o navegador.
- Banco, worker e aplicação não publicam portas no host: apenas o serviço `app` (porta `8000`) é
  roteado pelo Traefik do Dokploy na `dokploy-network`.

O repositório é público: nunca envie seu `.env`, a pasta `backups/` ou a pasta `data/`.

## Desenvolvimento

Backend em Python 3.12 (FastAPI, SQLAlchemy, worker assíncrono) e frontend em React,
TypeScript e Tailwind.

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/bin/python -m pytest
```

API em modo de desenvolvimento (SQLite em `backend/data/`):

```bash
cd backend && ADMIN_PASSWORD=troque-esta-senha .venv/bin/uvicorn app.main:app --reload
```

Em outro terminal, o monitor:

```bash
cd backend && .venv/bin/python -m app.worker
```

Interface com recarga automática:

```bash
cd frontend && npm install && npm run dev
```

```
backend/app/
  sources/   um coletor por loja ou fonte
  core/      relevância, variantes, motor de oportunidades e radar
  notify/    push, e-mail e WhatsApp
  api/       rotas HTTP
  worker.py  agendador contínuo
frontend/src/  interface (PWA)
```

Para adicionar uma loja, implemente `StoreSource.search` (ou `FeedSource.fetch`) em
`sources/`, registre em `sources/registry.py` e inclua um teste com uma amostra.

## Licença

Veja [LICENSE](LICENSE).
