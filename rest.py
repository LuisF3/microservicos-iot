from flask import Flask, request, make_response
from flask_cors import CORS
import pymongo
import datetime
import paho.mqtt.client as mqtt
import json
import bcrypt
import math

app = Flask(__name__)
CORS(app)


def on_message(client, userdata, msg):
    global db, sensor_temp, min_temp, max_temp
    cur_msg = str(msg.payload.decode("utf-8"))
    cur_msg = json.loads(cur_msg)
    print(msg.topic + " " + str(msg.payload))

    cur_msg['s'] = datetime.datetime.strptime(cur_msg['s'], "%d/%m/%Y %H:%M:%S")

    if msg.topic.startswith("1/temp/"):
        sensor_temp[msg.topic[-2:]] = int(cur_msg["temp"])
        db.temp_occur.insert_one(cur_msg)
        avg = get_temp()
        if avg >= max_temp:
            turn_air(True)
        elif math.isclose(avg, target_temp, abs_tol=0.5):
            turn_air(False)

    elif msg.topic.startswith("1/umid/"):
        db.umid_occur.insert_one(cur_msg)

def on_connect(client, userdata, flags, rc):
    global sensor_temp
    print(" * Connected with result code " + str(rc))

    for sensor_id in sensor_temp:
        print(f' * Subscribing to {sensor_id}')
        client.subscribe(f'1/temp/{sensor_id}')
        client.subscribe(f'1/umid/{sensor_id}')


global client_paho, db, mode, min_temp, max_temp, target_temp, sensor_temp, air_state

air_state = False
mode = False                                                              # modo de execução do controlador (False: automático, True: manual)
max_temp = 18                                                             # temperatura máxima desejada para a sala
min_temp = 16                                                             # temperatura mínima desejada para a sala
target_temp = 17                                                          # temperatura em que o ar-condicionado irá operar
sensor_temp = {"27": target_temp, "28": target_temp, "29": target_temp}   # temperatura medida pelos sensores

print(f' * Connecting to broker')
client_paho = mqtt.Client()
client_paho.on_connect = on_connect
client_paho.on_message = on_message
# client_paho.connect("localhost", 1883, 60)
client_paho.connect("andromeda.lasdpc.icmc.usp.br", 8041, 60)
db = pymongo.MongoClient("localhost", 27017).iot


def turn_air(to):
    global client_paho, db, min_temp, max_temp, target_temp, air_state
    if air_state == to:
        return
    air_state = to

    print(
        f'{"Ligando" if to else "Desligando"} o ar condicionado na temperatura {target_temp}; min: {min_temp}; max: {max_temp};')
    client_paho.publish("3/aircon/30",
                        str({"0": 1, "21": 1 if to else 0, "23": 1, "s": datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}), 2)


def get_temp():
    global sensor_temp
    avg = 0
    for value in sensor_temp.values():
        avg += value
    avg /= len(sensor_temp)
    return avg


def make_error(status_code=200, message="error"):
    return make_response({"status_code": status_code, "message": message}, status_code)


@app.route('/set-temperature', methods=['POST'])
def set_temperature():
    global client_paho, max_temp, min_temp, target_temp, mode, air_state

    # modo automático
    if mode == False:
        if request.json["max"] < 17 or request.json["max"] > 23:
            return make_error(400, "Temperatura máxima fora dos limites [17,23]")
        if request.json["min"] < 16 or request.json["min"] > 22:
            return make_error(400, "Temperatura mínima fora dos limites [16,22]")
        if request.json["max"] < request.json["min"]:
            return make_error(400, "Temperatura máxima deve ser superior à mínima")
        min_temp = request.json["min"]
        target_temp = request.json["min"]
        max_temp = request.json["max"]

    # modo manual
    else: 
        if request.json["target"] < 16 or request.json["max"] > 23:
            return make_error(400, "Temperatura fora dos limites [16,23]")
        target_temp = request.json["target"]
        turn_air(True)

    return {"max": max_temp, "min": min_temp, "target": target_temp, "airStatus": air_state, "airMode": mode}


@app.route('/mode', methods=['GET', 'POST'])
def set_manual():
    global mode
    if request.method == 'POST':
        mode = request.json["mode"]
        return {"mode": mode}
    elif request.method == 'GET':
        return {"mode": mode}


@app.route('/temp-avg', methods=['GET', 'POST'])
def temperature_avg():
    global db
    period = int(request.args.get('period'))
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

    rows = list (db.temp_occur.aggregate(pipeline))

    avg = 0

    for value in rows:
        avg += value['temp']
    avg /= len(rows)

    return {"avg": avg}


@app.route('/api/auth', methods=['POST'])
def authenticate_user():
    global db
    username = request.json['username']
    password = request.json['password'].encode('utf-8')
    
    user = db.users.find_one({'username': username})

    if user and bcrypt.checkpw(password, user['password']):
        del user['_id']
        del user['password']
        user['token'] = str(user['token'])[2:-1]

        return {
            "mqtt": {
                "url": "ws://andromeda.lasdpc.icmc.usp.br:9999",
                "host": "andromeda.lasdpc.icmc.usp.br",
                "port": "9999"
            },
            "microsservice": {
                "host": "andromeda.lasdpc.icmc.usp.br",
                "port": "5000",
                "APIKEY": user['token']
            }
        }
    else:
        return make_error(401, 'Username or password are incorrect')

@app.route('/api/new-auth', methods=['POST'])
def create_user():
    global db
    username = request.json['username']
    password = request.json['password'].encode('utf-8')
    
    user = db.users.find_one({'username': username})
    if user:
        return make_error(400, 'This username is invalid')

    db.users.insert_one({'username': username, 'password': bcrypt.hashpw(password, bcrypt.gensalt()), 'token': bcrypt.gensalt()})
    
    user = db.users.find_one({'username': username})
    del user['_id']
    del user['password']

    user['token'] = str(user['token'])[2:-1]

    return user

@app.route('/sensor-history', methods=['GET'])
def sensor_history():
    global db

    if request.args.get('topic') is None:
        return make_error(400, 'Sensor topic required')

    period = int(request.args.get('period'))
    results_filtered = []
    now = datetime.datetime.now()

    hour = now.hour - period % 24
    day = now.day - math.floor(period/24) - (1 if hour < 0 else 0)
    if hour < 0:
        hour += 24

    print(now)
    now = now.replace(day=day, hour=hour)
    print(now)

    if request.args.get('topic') == 'temp':
        query = {
            's': {'$gte': now},
        }
        results = list(db.temp_occur.find(query))
        for i in range(0, len(results), 30):
            avg = 0
            for j in range(i, min(i+30, len(results))):
                avg += results[j]['temp']
            avg /= min(30, len(results) - i)
            results[i]['s'] = results[i]['s'].strftime("%d/%m/%Y, %H:%M:%S")
            results[i]['temp'] = avg
            del(results[i]['_id'])
            results_filtered.append(results[i])

    elif request.args.get('topic') == 'umid':
        query = {
            's': {'$gte': now},
        }
        results = list(db.umid_occur.find(query))
        for i in range(0, len(results), 30):
            avg = 0
            for j in range(i, min(i+30, len(results))):
                avg += results[j]['umid']
            avg /= min(30, len(results) - i)
            results[i]['s'] = results[i]['s'].strftime("%d/%m/%Y, %H:%M:%S")
            results[i]['umid'] = avg
            del(results[i]['_id'])
            results_filtered.append(results[i])
        
    return {
        'size': len(results_filtered),
        'results': results_filtered
    }


@app.route('/api/air-information', methods=['GET'])
def get_air_info():
    global max_temp, min_temp, target_temp, mode, air_state

    return {
        "max": max_temp,
        "min": min_temp,
        "target":target_temp,
        "airMode": mode,
        "airStatus" : air_state
    }

client_paho.loop_start()
app.run()