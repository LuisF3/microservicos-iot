# microservicos-iot

## Alunos (Time 3):
- Henrique Tadashi Tarzia - 10692210
- Luis Felipe Ribeiro Chaves - 10801221
- Victor Akihito Kamada Tomita - 10692082

## Instalação e Dependências
Para executar a aplicação, será necessária a instalação de bibliotecas python para efetuar conexão com o broker e gerenciar o banco de dados.  Antes disso, recomenda-se a criação de um ambiente virtual (venv), realizada através dos seguintes comandos:
- python3 -m venv venv (criação de instância da venv)
- source venv/bin/activate  (ativação do ambiente virtual)

Uma vez presente na pasta da venv recém criada, execute o comando "pip install -r requirements.txt" com o arquivo de texto na pasta para instalação das bibliotecas utilizadas pela aplicação. Por fim, insira o comando "python3 rest.py" no terminal para iniciar o programa. Vale mencionar que são exigidas a execução prévia de uma instância do broker mosquitto e do banco de dados MongoDB.

## Programa em execução
O sistema funciona de duas maneiras, manual ou automático, configuração a qual pode ser alterada na rota <code>/mode</code>. Quando manual, o sistema simplesmente repassa os dados enviados na rota <code>/set-temperature</code> e, quando automático, realiza a média da temperatura coletada pelos sensores configurados em sensor_temp, utilizando as informações recebidas através da rota <code>1/temp/</code> para mensurar a temperatura atual da sala e definir o estado de ativação do ar condicionado (ligado/desligado) através da rota <code>3/aircon/30</code>, tomando como critério um intervalo de valores mínimo e máximo desejados. Por meio da rota <code>/temp-avg</code>, é possível receber a temperatura média no período de tempo declarado no campo <code>period</code> da requisição (em horas). Sempre que houver o recebimento de informações vinculadas à temperatura captada pelos sensores, será realizada uma inserção no banco de dados contendo temperatura e data com horário da coleta.
