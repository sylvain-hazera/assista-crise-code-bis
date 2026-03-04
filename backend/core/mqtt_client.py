import os
import paho.mqtt.client as mqtt

# Récupération des variables d'environnement
MQTT_BROKER = os.environ.get("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER = os.environ.get("MQTT_USER", "backend_user")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

# Le topic par défaut de Meshtastic (à adapter selon ta config LoRa)
MQTT_TOPIC = "msh/EU_868/2/json/#"

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Backend connecté avec succès au broker Mosquitto !")
        client.subscribe(MQTT_TOPIC)
        print(f"En écoute sur le topic : {MQTT_TOPIC}")
    else:
        print(f"Échec de la connexion MQTT, code : {reason_code}")

def on_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8')
    print(f"Nouveau message LoRa reçu sur {msg.topic}:")
    print(payload)
    # TODO : Parser le JSON de Meshtastic, extraire les coordonnées/demandes
    # et les insérer dans ta base de données PostgreSQL.

def start_mqtt_client():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        # loop_start() fait tourner le client dans un thread séparé
        client.loop_start()
    except Exception as e:
        print(f"Erreur de connexion au broker MQTT : {e}")