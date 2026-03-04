from django.apps import AppConfig
import os
import traceback # <-- Ajout très important pour voir la vraie erreur

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        print("====== 1. CHARGEMENT DE L'APP CORE ======")
        
        if os.environ.get('RUN_MAIN') == 'true':
            print("====== 2. TENTATIVE DE LANCEMENT DU CLIENT MQTT ======")
            try:
                # Importation absolue plutôt que relative
                from core.mqtt_client import start_mqtt_client
                start_mqtt_client()
                print("====== 3. CLIENT MQTT LANCÉ EN TÂCHE DE FOND ======")
            except ImportError as e:
                print(f"====== ERREUR D'IMPORTATION : {e} ======")
                traceback.print_exc() # Affiche la ligne exacte du plantage
            except Exception as e:
                print(f"====== ERREUR FATALE MQTT : {e} ======")
                traceback.print_exc()