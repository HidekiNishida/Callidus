# Qualidade da entrega

Como transformar um pedido em uma entrega completa, funcional e comprovada.

Voltar ao [hub de engenharia](README.md) · [Índice da documentação](/docs/README.md)

## 🧭 Contrato antes do trabalho

Antes de planejar, converta o pedido em um contrato curto:

| Campo | Pergunta que precisa responder |
|-------|--------------------------------|
| Resultado | O que a pessoa poderá usar ou decidir ao final? |
| Artefatos | Quais arquivos, páginas, documentos, dados ou alterações são esperados? |
| Comportamento | O que cada parte precisa fazer, inclusive estados vazios e erros? |
| Restrições | O que deve ser preservado, evitado ou tratado como hipótese? |
| Aceite | Que observação concreta demonstra que cada requisito funciona? |

Quando o pedido deixa uma decisão de baixo risco aberta, escolha uma opção coerente e registre-a. Não transforme isso em uma pergunta que interrompe o trabalho. Decisões protegidas continuam seguindo [AGENTS.md §17](/AGENTS.md#17-decisões-do-dono).

## 🔗 Rastreabilidade e evidência

Mantenha uma linha por requisito, ligando requisito, artefato, verificação e resultado. Evidência de outro arquivo, execução antiga ou critério genérico não prova o requisito atual.

| Requisito | Artefato | Verificação adequada |
|-----------|----------|----------------------|
| Criar ou editar um arquivo nomeado | Caminho explicitamente pedido | Arquivo existe e a evidência aponta para esse caminho |
| Alterar código | Símbolo e contrato afetados | Teste de comportamento e lint/sintaxe pertinentes |
| Criar página ou interface | Rotas, componentes e recursos da página | Abrir em navegador; verificar conteúdo, erros, interações e tamanhos de tela relevantes |
| Criar documento ou planilha | Arquivo final e estrutura pedida | Abrir/renderizar e conferir conteúdo e legibilidade |
| Produzir dado ou análise | Saída e origem dos dados | Conferir cálculos, limites, proveniência e casos vazios |

Uma verificação só pode aprovar o que inspecionou. O aceite deve falhar quando o pedido nomeia `style.css`, mas a única evidência cobre `index.html`, mesmo que exista texto genérico de sucesso. Para interfaces, captura de tela demonstra apresentação, mas não prova que botões, formulários, navegação e estados de erro funcionam.

## 🧪 Perfil de qualidade proporcional

Escolha as verificações pelo risco e pela natureza do resultado. Evite tanto a aprovação superficial quanto a inclusão de infraestrutura que o pedido não exige.

| Tipo de entrega | Verificações mínimas |
|-----------------|----------------------|
| Código | Sintaxe/importação ou build aplicável, comportamento central, falhas relevantes e integração no ponto de uso |
| Site/interface | Conteúdo completo, links e controles ativos, feedback de formulário, console limpo, recursos carregados ou fallback, teclado e layout estreito/largo |
| Documento/apresentação | Arquivo abre, seções pedidas presentes, render legível e sem cortes/elementos sobrepostos |
| Planilha/dados | Fórmulas e referências conferidas, totais reconciliados, formatos/unidades e células vazias tratados |
| Pesquisa/análise | Fontes rastreáveis, fatos separados de inferências, recorte temporal explícito quando necessário |

O contrato do Callidus seleciona pisos iniciais para engenharia de software, web, documentos, planilhas, apresentações e pesquisa. Esses critérios guiam o plano e a execução; sua presença no prompt **não é prova** de que o arquivo final passou por renderização, recálculo ou checagem de fontes. G16 acompanha os verificadores independentes que ainda faltam para essas classes.

Teste a jornada principal de ponta a ponta. Depois cubra o caso vazio, uma entrada inválida e a falha externa mais provável. Faça uma revisão visual e de acessibilidade básica quando houver interface. Não declare um serviço conectado, envio concluído ou dado atualizado sem evidência desse efeito.

## 🔁 Recuperação sem repetição cega

Quando uma verificação falhar, registre o critério, o caminho inspecionado, a evidência observada e uma hipótese de causa. A próxima tentativa precisa mudar a ação com base nessa hipótese. Após repetição sem progresso, interrompa o ciclo, preserve o estado e reporte o que falta como incompleto. Replanejar ou encontrar um arquivo não substitui a entrega pedida.

O agente que executa não é a única fonte de aprovação: use verificações determinísticas, testes e revisão independente disponíveis. Se um método de verificação não cobre a propriedade (por exemplo, sintaxe não prova usabilidade), isso deve aparecer como limite e não como aceite.

## ✅ Fechamento

Antes de marcar concluído, confirme:

- cada artefato pedido existe no local esperado e corresponde ao escopo;
- cada critério observável tem evidência recente e ligada à entrega;
- fluxos centrais funcionam e erros dão feedback compreensível;
- conteúdo e apresentação estão completos para o público e idioma do pedido;
- documentação, índices, progresso e estado da tarefa refletem o que foi realmente verificado;
- limitações remanescentes estão explícitas e o status final não promete além da evidência.

Essa prática complementa os [portões de engenharia](/docs/engineering/quality-gates.md) e o [protocolo de verificação](/docs/architecture/requisitos-verificacao-progresso.md). Ela não altera critérios de produto ou estágio sem decisão do dono.
