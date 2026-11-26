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

## Subindo no VPS

Requisitos: Linux com Docker e Docker Compose, cerca de 1 GB de RAM livre (mais ~500 MB se usar
o WhatsApp pelo WAHA) e as portas 80 e 443 liberadas.

```bash
git clone https://github.com/joaovictorsouza/bftracker.git
```

```bash
cd bftracker
```

Gere o `.env` com senhas aleatórias, informando o domínio que aponta para o VPS:

```bash
./scripts/setup.sh ofertas.seudominio.com voce@exemplo.com
```

```bash
docker compose up -d --build
```

Acesse `https://ofertas.seudominio.com`, entre com o usuário `admin` e a senha mostrada pelo
script, e troque a senha em **Configurações**.

### Domínio e HTTPS

O navegador só permite **notificações push em HTTPS**. O Caddy incluído emite o certificado
sozinho quando `SITE_ADDRESS` é um domínio. Sem domínio próprio, use o
[sslip.io](https://sslip.io): para o IP `203.0.113.10`, informe `203-0-113-10.sslip.io`.

Sem argumento, o `setup.sh` sobe em `http://IP-do-servidor` (porta 80). Serve para um teste
rápido, mas a senha trafega sem criptografia e o push não funciona.

Já tem um proxy reverso (Nginx, Traefik) usando as portas 80/443? Defina no `.env`
`HTTP_PORT=8080`, `HTTPS_PORT=8443`, `SITE_ADDRESS=:80` e aponte o proxy para a porta 8080,
repassando `X-Forwarded-Proto` e sem buffer em `/api/events`. Nesse caso, ajuste o `Caddyfile`
para confiar no seu proxy
([`trusted_proxies`](https://caddyserver.com/docs/caddyfile/options#trusted-proxies)).

## Configurando os avisos

Tudo pode ser configurado em **Configurações → Integrações** (segredos ficam cifrados no banco)
ou pelo `.env`.

### Push no celular

1. Abra o BFTracker no celular por HTTPS.
2. **iPhone/iPad:** Compartilhar → *Adicionar à Tela de Início* e abra pelo ícone (iOS 16.4+).
3. Toque em **Ativar push** e depois em **Testar**.

As chaves VAPID são geradas automaticamente no primeiro início.

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

## Fontes de ofertas

| Grupo | Fontes |
| --- | --- |
| Comparadores (trazem Amazon, Magalu, Casas Bahia, Mercado Livre, Fast Shop etc.) | Zoom, Buscapé |
| Lojas consultadas diretamente | Amazon, KaBuM!, Americanas, Samsung, Motorola, Electrolux, Brastemp, Compra Certa, Sam's Club, Webcontinental, Casa & Video |
| Usados e recondicionados | OLX, Trocafone, Mercado Livre (API), itens usados da Amazon, KaBuM! e Americanas |
| Radar: sites | TudoCelular, Canaltech, Tecnoblog, Adrenaline, Mundo Conectado, MeuPlayStation |
| Radar: comunidades | Promobit (ofertas e cupons por loja), hardMOB Promoções |
| Radar: canais públicos do Telegram | Pelando, Pechinchou, Nerd Ofertas, Achados do Tecnoblog, TudoCelular, Baita Compra Tech, Ofertas Adrenaline, Bench Promos, Seletronic, PromoTop, PC do Fafa, KaBuM! |
| Qualquer loja | Monitoramento por link (dados schema.org/Open Graph da página) |

Você pode acrescentar canais do Telegram, feeds RSS e lojas VTEX em **Configurações → Fontes**.
Os canais são atualizados a cada ~75 s, os fóruns e agregadores a cada 2–3 min e os feeds a
cada 4 min.

### Limitações reais (leia antes)

Teste no seu servidor quais fontes respondem:

```bash
docker compose exec app python -m app.cli check-sources ps5
```

Na validação de **25/11/2026**, a partir de uma conexão residencial:

- **OLX** e **hardMOB** recusaram o acesso automatizado (HTTP 403). Os coletores existem e são
  testados com amostras, mas **não foram validados contra o site ao vivo pelo aplicativo**. Pode
  ser diferente no IP do seu VPS. Enquanto estiver bloqueada, a aba *Usados* oferece atalhos para
  abrir a busca na OLX, Mercado Livre, Enjoei e Facebook Marketplace.
- **Mercado Livre** exige credenciais da API oficial para busca direta
  ([developers.mercadolivre.com.br](https://developers.mercadolivre.com.br)). Essa integração
  segue a documentação, mas **não foi testada com credenciais reais**. Sem elas, ofertas e cupons
  do Mercado Livre chegam pelos comparadores, Promobit e canais.
- **Magazine Luiza** e **Casas Bahia** barram consultas diretas; os preços chegam pelos
  comparadores e pelo radar.
- **Amazon** às vezes limita requisições (HTTP 503); o monitor espera e tenta de novo.
- Cupons relâmpago são detectados quando alguma fonte os publica; a página de cupons do Mercado
  Livre exige login e não é acessada.
- Páginas mudam. Quando um coletor parar, o erro aparece em **Configurações → Fontes**.

O BFTracker se identifica no `User-Agent`, limita a frequência por domínio, recua quando é
bloqueado e **não contorna CAPTCHA nem proteções anti-robô**. Use para fins pessoais e respeite
os termos de cada site. Alguns restringem coleta automatizada: o `robots.txt` do Zoom e do
Buscapé, por exemplo, pede que robôs não usem a busca (`?q=`). A decisão é sua; qualquer fonte
pode ser desligada em **Configurações → Fontes**.

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
- Banco e aplicação não publicam portas: só o Caddy fica exposto.

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
