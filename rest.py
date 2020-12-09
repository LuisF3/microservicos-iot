from flask import Flask, request, make_response, send_from_directory
from flask_cors import CORS
import pymongo
import datetime
import paho.mqtt.client as mqtt
import json
import bcrypt
import math
import uuid
import os

app = Flask(__name__, static_folder='build')
CORS(app)

# Realiza o processamento das mensagens de acordo com o tópico 
# @param client: instância do cliente mqtt 
# @param msg: mensagem recebida por um dos tópicos
def on_message(client, userdata, msg):
    global mode, db, sensor_temp, min_temp, max_temp
    print(msg.topic + " " + str(msg.payload))
    cur_msg = str(msg.payload.decode("utf-8"))
    cur_msg = json.loads(cur_msg)

    # Converte o valor referente à data recebida para o tipo datetime 
    cur_msg['s'] = datetime.datetime.strptime(cur_msg['s'], "%d/%m/%Y %H:%M:%S")

    # Para cada mensagem, verifica a qual tópico ela pertence e realiza a inserção na tabela correspondente
    # do banco de dados. No caso do tópico de temperatura, avalia a média das temperaturas coletadas pelos sensores
    # para realizar o controle da ativação do ar-condicionado. 

    # Tópico temperatura
    if msg.topic.startswith("1/temp/"):
        sensor_temp[msg.topic[-2:]] = int(cur_msg["temp"])
        db.temp_occur.insert_one(cur_msg)
        if not mode:
            avg = get_temp()
            # Caso a temperatura atual seja superior ao limite máximo especificado, liga o ar
            if avg >= max_temp:
                turn_air(True)
            # Caso a temperatura atual esteja próxima da ideal, desliga o ar
            elif math.isclose(avg, target_temp, abs_tol=0.5):
                turn_air(False)
    # Tópico umidade
    elif msg.topic.startswith("1/umid/"):
        db.umid_occur.insert_one(cur_msg)
    # Tópico movimento
    elif msg.topic.startswith("1/movimento/"):
        db.movimento_occur.insert_one(cur_msg)
    # Tópico luz
    elif msg.topic.startswith("1/luz/"):
        db.luz_occur.insert_one(cur_msg)
    # Tópico de resposta do ar-condicionado
    elif msg.topic == "3/response":
        db.air_response.insert_one(cur_msg)
    # Outros tópicos
    else:
        db.others.insert_one(cur_msg)

# Inscreve a aplicação nos tópicos necessários para o recebimento de dados 
# @param client: instância do cliente mqtt
def on_connect(client, userdata, flags, rc):
    global sensor_temp, sensor_umid, sensor_movimento, sensor_luz
    print(" * Connected with result code " + str(rc))
    # Tópico temperatura
    for sensor_id in sensor_temp:
        print(f' * Subscribing to 1/temp/{sensor_id}')
        client.subscribe(f'1/temp/{sensor_id}')
    # Tópico umidade
    for sensor_id in sensor_umid:
        print(f' * Subscribing to 1/umid/{sensor_id}')
        client.subscribe(f'1/umid/{sensor_id}')
    # Tópico movimento
    for sensor_id in sensor_movimento:
        print(f' * Subscribing to 1/movimento/{sensor_id}')
        client.subscribe(f'1/movimento/{sensor_id}')
    # Tópico luz
    for sensor_id in sensor_luz:
        print(f' * Subscribing to 1/luz/{sensor_id}')
        client.subscribe(f'1/luz/{sensor_id}')

    #print(f' * Subscribing to 3/response')
    #client.subscribe(f'3/response')
    

global client_paho, db, mode, min_temp, max_temp, target_temp, sensor_temp, air_state

air_state = False
mode = False                                                              # modo de execução do controlador (False: automático, True: manual)
max_temp = 18                                                             # temperatura máxima desejada para a sala
min_temp = 16                                                             # temperatura mínima desejada para a sala
target_temp = 17                                                          # temperatura em que o ar-condicionado irá operar
sensor_temp = {"27": target_temp, "28": target_temp, "29": target_temp}   # temperatura medida pelos sensores
sensor_umid = [27,28,29]                                                  # identificadores dos sensores de umidade
sensor_movimento = [32]                                                   # identificador(es) do(s) sensor(es) de movimento
sensor_luz = [33]                                                         # identificador(es) do(s) sensor(es) de luz

print(f' * Connecting to broker')
client_paho = mqtt.Client()
client_paho.on_connect = on_connect
client_paho.on_message = on_message
client_paho.connect("andromeda.lasdpc.icmc.usp.br", 8041, 60)
db = pymongo.MongoClient("localhost", 27017).team3

def authenticate(token):
    global db
    user = db.users.find_one({"token": token})
    return user 

# Define o estado do ar-condicionado (ligado/desligado)
# @param to: estado de ativação 
def turn_air(to):
    global client_paho, db, min_temp, max_temp, target_temp, air_state
    # Estado  
    if air_state == to:
        return
    # Atualiza o estado atual
    air_state = to
    # Publica a modificação no tópico de controle do ar-condicionado
    print(
        f'{"Ligando" if to else "Desligando"} o ar condicionado na temperatura {target_temp}; min: {min_temp}; max: {max_temp};')
    print('Publicando o seguinte json: ' + json.dumps({"0": 1, "21": 1 if to else 0, "23": 1, "s": datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}))
    client_paho.publish("3/aircon/30",
                        json.dumps({"0": 1, "21": 1 if to else 0, "23": 1, "s": datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}), 2)

# Estima a temperatura atual da sala 
# @return avg: temperatura média da última coleta efetuada pelos sensores
def get_temp():
    global sensor_temp
    avg = 0
    for value in sensor_temp.values():
        avg += value
    avg /= len(sensor_temp)
    return avg

# Define um estado de erro customizado para a aplicação 
# @param status_code: código do erro
# @param message: mensagem de erro
# @return: erro com os valores dos parâmetros de entrada
def make_error(status_code=200, message="error"):
    return make_response({"status_code": status_code, "message": message}, status_code)

# Modifica os parâmetros de temperatura e ativação do ar-condicionado de acordo com o modo de controle (manual/automático)
# @return: json contendo o valor dos parâmetros atualizados
@app.route('/set-temperature', methods=['POST'])
def set_temperature():
    global client_paho, max_temp, min_temp, target_temp, mode, air_state

    if not authenticate(request.args.get("APIKEY")):
        return make_error(401, "Invalid token")

    mode = True if request.args["airMode"] == 'manual' else False

    # Modo automático
    if not mode:
        local_max = float(request.args["max"])
        local_min = float(request.args["min"])
        # Avaliação do intervalo de valores válidos para a temperatura máxima
        if local_max < 17 or local_max > 23:
            return make_error(400, "Temperatura máxima fora dos limites [17,23]")
        # Avaliação do intervalo de valores válidos para a temperatura mínima
        if local_min < 16 or local_min > 22:
            return make_error(400, "Temperatura mínima fora dos limites [16,22]")
        # Temperatura máxima não pode ser inferior à mínima
        if local_max < local_min:
            return make_error(400, "Temperatura máxima deve ser superior à mínima")
        # Atualização dos valores armazenados na aplicação
        min_temp = local_min
        target_temp = local_min
        max_temp = local_max
        # Verifica se o novo limite superior é menor ou igual à temperatura ambiente
        if get_temp() >= max_temp:
            turn_air(True)
    # Modo manual
    else: 
        local_target = float(request.args["target"])
        local_airStatus = True if request.args["airStatus"] == '1' else False
        # Avaliação do intervalo de valores válidos para a temperatura máxima
        if local_target < 16 or local_target > 23:
           return make_error(400, "Temperatura fora dos limites [16,23]")
        # Atualização da temperatura ideal 
        target_temp = local_target
        turn_air(local_airStatus)

    return {"max": max_temp, "min": min_temp, "target": target_temp, "airStatus": air_state, "airMode": mode}

# Retorna o método de gerenciamento do ar-condicionado (manual/automático), modificando seu valor quando especificado
# @return: json com o modo de controle atualizado
@app.route('/mode', methods=['GET', 'POST'])
def set_manual():
    global mode, max_temp

    if not authenticate(request.args.get("APIKEY")):
        return make_error(401, "Invalid token")

    if request.method == 'POST':
        mode = request.json["mode"]
        if not mode and get_temp() >= max_temp:
            turn_air(True)
        return {"mode": mode}
    elif request.method == 'GET':
        return {"mode": mode}

# Calcula a média das temperaturas no período de tempo especificado na requisição
# @return: json com o resultado da média
@app.route('/temp-avg', methods=['GET', 'POST'])
def temperature_avg():
    global db

    if not authenticate(request.args.get("APIKEY")):
        return make_error(401, "Invalid token")

    period = int(request.args.get('period'))
    # Especifica consulta ao banco às linhas que se encontram dentro do período desejado
    pipeline = (
        [
            {
                '$project': {
                    's': '$s',
                    '0': '$0',
                    'temp': '$temp',
                    'inside_given_period': {
                        '$lte': [{'$subtract': [datetime.datetime.now(), '$s']}, period * 3600000]},
                }
            },
            {
                '$match': {
                    'inside_given_period': True
                }
            }
        ]
    )

    # Recebe lista com a linhas que atendam ao critério de consulta
    rows = list (db.temp_occur.aggregate(pipeline))

    avg = 0
    # Calcula a média dos valores obtidos na consulta
    for value in rows:
        avg += value['temp']
    avg /= len(rows)

    return {"avg": avg}

# Autentica login de usuário
# @return: json contendo localização do broker e da aplicação de microsserviços, bem como o token do usuário
@app.route('/api/auth', methods=['POST'])
def authenticate_user():
    global db
    username = request.json['username']
    password = request.json['password'].encode('utf-8')
    # Procura nome do usuário no banco de dados
    user = db.users.find_one({'username': username})
    # Verifica a existência do usuário e a validade da senha 
    if user and bcrypt.checkpw(password, user['password']):
        del user['_id']
        del user['password']

        return {
            "mqtt": {
                "url": "ws://andromeda.lasdpc.icmc.usp.br:9999",
                "host": "andromeda.lasdpc.icmc.usp.br",
                "port": "9999"
            },
            "microsservice": {
                "APIKEY": user['token']
            }
        }
    else:
        return make_error(401, 'Username or password are incorrect')

# Cria um novo usuário
# @return user: json contendo o nome do usuário e o token de autenticação
@app.route('/api/new-auth', methods=['POST'])
def create_user():
    global db
    # Coleta valores da requisição para o registro do usuário
    username = request.json['username']
    password = request.json['password'].encode('utf-8')
    # Verifica a existência prévia de um usuário com mesmo nome
    user = db.users.find_one({'username': username})
    if user:
        return make_error(400, 'This username is invalid')
    # Insere os dados no banco, encriptando senha e token
    db.users.insert_one({'username': username, 'password': bcrypt.hashpw(password, bcrypt.gensalt()), 'token': str(uuid.uuid4())})
    # Procura pelo usuário recém inserido
    user = db.users.find_one({'username': username})
    # Remove os atributos desnecessários para o retorno da função
    del user['_id']
    del user['password']

    return user

# Coleta histórico de um sensor dentro do período desejado (em horas)
# @return: json com os resultados da consulta e a quantidade de valores nela presentes 
@app.route('/sensor-history', methods=['GET'])
def sensor_history():
    global db

    if not authenticate(request.args.get("APIKEY")):
        return make_error(401, "Invalid token")

    # Tópico do sensor não especificado
    if request.args.get('topic') is None:
        return make_error(400, 'Sensor topic required')

    period = int(request.args.get('period'))    # Período declarado no campo da requisição
    results_filtered = []                       # Lista com os resultados encontrados
    now = datetime.datetime.now()               # Tempo atual

    # Atualiza dia e hora mínimos para aceitação
    hour = now.hour - period % 24
    day = now.day - math.floor(period/24) - (1 if hour < 0 else 0)
    if hour < 0:
        hour += 24

    print(now)
    now = now.replace(day=day, hour=hour)
    print(now)

    # Tópico temperatura
    if 'temp' in request.args.get('topic'):
        query = {
            's': {'$gte': now},
        }
        # Recebe as linhas de data igual ou posterior à mínima
        results = list(db.temp_occur.find(query))
        # Calcula a média de 30 resultados em função do curto período de coleta de dados dos sensores 
        for i in range(0, len(results), 90):
            avg = 0
            for j in range(i, min(i+90, len(results))):
                avg += results[j]['temp']
            avg /= min(90, len(results) - i)
            # Atualiza valores do primeiro elemento do intervalo para facilitar a inserção posterior
            results[i]['s'] = results[i]['s'].strftime("%d/%m/%Y %H:%M:%S")
            results[i]['temp'] = avg
            del(results[i]['_id'])
            # Insere na lista de resultados final
            results_filtered.append(results[i])

    # Tópico umidade
    elif 'umid' in request.args.get('topic'):
        query = {
            's': {'$gte': now},
        }
        # Recebe as linhas de data igual ou posterior à mínima
        results = list(db.umid_occur.find(query))
        # Calcula a média de 30 resultados em função do curto período de coleta de dados dos sensores 
        for i in range(0, len(results), 90):
            avg = 0
            for j in range(i, min(i+90, len(results))):
                avg += results[j]['umid']
            avg /= min(90, len(results) - i)
            # Atualiza valores do primeiro elemento do intervalo para facilitar a inserção posterior
            results[i]['s'] = results[i]['s'].strftime("%d/%m/%Y %H:%M:%S")
            results[i]['umid'] = avg
            del(results[i]['_id'])
            # Insere na lista de resultados final
            results_filtered.append(results[i])
        
    return {
        'size': len(results_filtered),
        'results': results_filtered
    }

# Retorna todas as informações relacionadas ao ar-condicionado
# @return: json contendo os valores atuais de cada parâmetro
@app.route('/air-information', methods=['GET'])
def get_air_info():
    global max_temp, min_temp, target_temp, mode, air_state

    if not authenticate(request.args.get("APIKEY")):
        return make_error(401, "Invalid token")

    return {
        "max": max_temp,
        "min": min_temp,
        "target":target_temp,
        "airMode": 'auto' if mode else 'manual',
        "airStatus": air_state
    }

# Serve React App
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

client_paho.loop_start()
app.run(host="0.0.0.0", port=9001, debug=True)
