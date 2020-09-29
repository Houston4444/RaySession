#!/bin/bash

case "$LANG" in
    en_*)
        tr_script_info_loadanyway(){
            echo "<p><em>To open this session anyway,<br>"
            echo "de-activate session scripts.</em></p>"
        }
        
        tr_start_jack_failed_load(){
            echo "<p>Failed to start JACK."
            echo "Session open cancelled !</p>"
            tr_script_info_loadanyway
        }
        
        tr_start_jack_failed_close(){
            echo "<p>Failed to start JACK."
            echo "Your previous configuration can't be restored.</p>"
        }
        
        tr_device_not_connected_load(){
            echo "<p>Device <strong>$1</strong> is not connected !"
            echo "Session open cancelled.</p>"
            tr_script_info_loadanyway
        }
        
        tr_device_not_connected_close(){
            echo "<p>Device <strong>$1</strong> is not connected !"
            echo "Your previous configuration can't be restored.</p>"
        }
        
        tr_waiting_jack_infos="Waiting for JACK infos..."
        tr_starting_jack="Starting JACK"
        tr_stopping_clients="Stopping clients"
        tr_stopping_jack="Stopping JACK"
        tr_reconfigure_pulseaudio="Reconfigure PulseAudio"
        ;;
        
    fr_*)
        tr_script_info_loadanyway(){
            echo "<p><em>Pour ouvrir cette session malgré tout,<br>"
            echo "désactivez les scripts de session.</em></p>"
        }
        
        tr_start_jack_failed_load(){
            echo "<p>Échec du démarrage de JACK."
            echo "L'ouverture de la session est abandonnée.</p>"
            tr_script_info_loadanyway
        }
        
        tr_start_jack_failed_close(){
            echo "<p>Échec du démarrage de JACK."
            echo "Votre ancienne configuration n'a pas pu être restaurée.</p>"
        }
        
        tr_device_not_connected_load(){
            echo "<p>L'interface <strong>$1</strong> n'est pas connectée !<br>"
            echo "L'ouverture de la session est abandonnée.</p>"
            tr_script_info_loadanyway
        }
        
        tr_device_not_connected_close(){
            echo "L'interface $1 n'est pas connectée !"
            echo "Votre ancienne configuration n'a pas pu être restaurée."
        }
        
        tr_waiting_jack_infos="Attente des infos de JACK..."
        tr_starting_jack="Démarrage de JACK"
        tr_stopping_clients="Arrêt des clients"
        tr_stopping_jack="Arrêt de JACK"
        tr_reconfigure_pulseaudio="Reconfiguration de PulseAudio"
        ;;
        
    * )
        tr_script_info_loadanyway(){
            echo "<p><em>To open this session anyway,<br>"
            echo "de-activate session scripts.</em></p>"
        }
        
        tr_start_jack_failed_load(){
            echo "<p>Failed to start JACK."
            echo "Session open cancelled !</p>"
            tr_script_info_loadanyway
        }
        
        tr_start_jack_failed_close(){
            echo "<p>Failed to start JACK."
            echo "Your previous configuration can't be restored.</p>"
        }
        
        tr_device_not_connected_load(){
            echo "<p>Device <strong>$1</strong> is not connected !"
            echo "Session open cancelled.</p>"
            tr_script_info_loadanyway
        }
        
        tr_device_not_connected_close(){
            echo "<p>Device <strong>$1</strong> is not connected !"
            echo "Your previous configuration can't be restored.</p>"
        }
        
        tr_waiting_jack_infos="Waiting for JACK infos..."
        tr_starting_jack="Starting JACK"
        tr_stopping_clients="Stopping clients"
        tr_stopping_jack="Stopping JACK"
        tr_reconfigure_pulseaudio="Reconfigure PulseAudio"
        ;;
esac
