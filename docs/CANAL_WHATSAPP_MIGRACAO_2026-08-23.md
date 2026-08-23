# Migração para Canal de WhatsApp — desenho (2026-08-23)

> Item 13 da Onda 2. Este documento é **desenho, não execução**: nenhuma linha de
> código foi escrita para isto, e a primeira etapa é uma verificação que pode
> derrubar o plano inteiro.

## Por que existe a pergunta

O grupo de WhatsApp tem **teto de 1.024 participantes**. A matemática do
diagnóstico v2 diz que a meta de R$ 1.000/mês exige ~750 membros na taxa atual, e
~1.250 a 1.500 assumindo decaimento de engajamento. Ou seja: **o teto do grupo
fica no meio do caminho da meta**, e não adianta otimizar aquisição para um
recipiente que estoura antes de chegar lá.

Canal de WhatsApp (o recurso de broadcast, JID `@newsletter`) não tem esse teto.

## O que se ganha, além do teto

1. **Contagem de seguidores pela plataforma.** Hoje a métrica de público é
   manual: o adapter Evolution não expõe participantes de grupo, e por isso o
   item 8 da Onda 1 terminou com um lembrete semanal pedindo ao dono para contar
   à mão. Canal tem contagem nativa — a métrica passaria de `informado_dono` para
   `medido_api`.
2. **O formato bate com o uso real.** O grupo já é usado como broadcast; canal é
   broadcast por definição, sem custo de moderação nem ruído de conversa.
3. **Menos atrito de entrada.** Entrar num canal não expõe o telefone do novo
   membro aos outros — objeção real em grupo de desconto.

## O que se perde ou arrisca

1. **Capacidade técnica não confirmada** — ver a etapa 1 abaixo. É o risco que
   mata o plano.
2. **A base não migra sozinha.** As 99 pessoas do grupo precisam ser convidadas e
   nem todas vão. Perder parte de uma base que converte para ganhar teto que
   ainda não se usa é troca ruim se feita de uma vez.
3. **Descoberta continua sendo o gargalo.** Canal não é buscável de forma útil;
   a aquisição segue dependendo de Instagram e do site. Migrar não traz público —
   só remove um teto futuro.
4. **Interação some.** Canal permite reação, não conversa. Se houver conversa no
   grupo hoje, ela acaba.
5. **Atribuição não melhora.** O `matt_word` continua sem voltar pelo painel do
   ML; a leitura de receita por canal segue por correlação temporal.

## Etapa 1 — verificar se o transporte suporta (bloqueante)

O ambiente roda **Evolution API 2.3.7** (`whatsappWebVersion 2.3000.1045840685`),
com o adapter falando `/message/sendText/{instancia}` e `/message/sendMedia/{instancia}`.

**Não confirmei se esta versão publica em canal.** Uma sondagem por GET nas rotas
de newsletter devolveu 404, mas isso não conclui nada — `/message/sendText`
também devolve 404 no mesmo teste, por ser rota POST com instância inexistente.

Critério de sucesso da etapa, a ser feito com um canal de teste:

1. Criar um canal de teste na conta de WhatsApp usada pela instância de envio.
2. Descobrir o JID (`...@newsletter`) — via `/chat/findChats` ou equivalente.
3. Enviar **texto** e **imagem** para esse JID pelo caminho que o adapter já usa.
4. Confirmar que a mensagem aparece no canal.

Se falhar: o caminho passa a ser atualizar a Evolution ou trocar o transporte,
e aí a migração deixa de ser tarefa de produto e vira tarefa de infraestrutura,
com outro custo. **Nada além desta etapa deve ser construído antes dela.**

## Etapa 2 — modelagem, se a etapa 1 passar

- Novo `SocialChannel` com `code='whatsapp_canal'` e `target` = JID do canal.
  Nada de reaproveitar o registro do grupo: as métricas precisam ficar separadas,
  e `Delivery` já tem `UNIQUE (offer, social_channel)`, o que dá isolamento de
  graça.
- Adapter: aceitar JID de canal na rota de envio. Se o Evolution exigir rota
  própria de newsletter, é uma função nova em `evolutionClient`, no mesmo formato
  de `sendText`/`sendMedia`.
- `MetricaCanalDiaria`: se a contagem de seguidores vier por API, registrar com
  `fonte=medido_api` e desligar o lembrete manual para este canal.

## Etapa 3 — piloto em paralelo

Publicar **nos dois** (grupo e canal) por duas semanas, com o mesmo conteúdo.

- O relatório semanal (`relatorio_receita_semanal --channel`) já separa por canal;
  a comparação sai de graça.
- O que se mede: seguidores ganhos por semana no canal, e se o volume de cliques
  do grupo cai quando as mesmas ofertas aparecem nos dois lugares.
- Custo: dobra o número de envios. Com ~99 pessoas isso não é risco de spam, mas
  é risco de cansaço de quem está nos dois.

## Etapa 4 — corte

Só depois do piloto: apontar o CTA do site, o link da bio e o post fixado para o
canal, e deixar o grupo como está — sem anunciar fechamento. Grupo esvazia
sozinho quando o conteúdo bom migra; forçar saída perde gente que só queria
continuar onde estava.

## Rollback

Em qualquer etapa: `SocialChannel.is_active=False` no canal novo. O grupo nunca
é tocado, então não há o que desfazer do lado que funciona hoje.

## O que precisa de decisão do dono antes de começar

- Se aceita o piloto em paralelo (é a parte que dobra envio).
- Identidade do canal: mesmo nome, mesma arte, mesma descrição do grupo?
- Se o grupo continua existindo depois do corte, e por quanto tempo.
