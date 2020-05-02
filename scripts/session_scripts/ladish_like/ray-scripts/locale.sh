#!/bin/bash

case "$LANG" in
    en_*)
        tr_reconfigure_pulseaudio(){
            echo "Reconfigure PulseAudio
with $1 inputs / $2 outputs."
        }

        tr_waiting_jack_infos="Waiting for JACK infos..."
        tr_starting_jack="Starting JACK"
        tr_start_jack_failed="Failed to start JACK.
Session open cancelled !"
        tr_stopping_clients="Stopping clients"
        tr_stopping_jack="Stopping JACK"
        ;;
        
    fr_*)
        tr_reconfigure_pulseaudio(){
            echo "Reconfiguration de PulseAudio
avec $1 entrées / $2 sorties."
        }

        tr_waiting_jack_infos="Attente des infos de JACK..."
        tr_starting_jack="Démarrage de JACK"
        tr_start_jack_failed="Échec du démarrage de JACK.
L'ouverture de la session est abandonnée !"
        tr_stopping_clients="Arrêt des clients"
        tr_stopping_jack="Arrêt de JACK" 
        ;;
        
    * )
        tr_reconfigure_pulseaudio(){
            echo "Reconfigure PulseAudio
with $1 inputs / $2 outputs."
        }

        tr_waiting_jack_infos="Waiting for JACK infos..."
        tr_starting_jack="Starting JACK"
        tr_start_jack_failed="Failed to start JACK.
Session open cancelled !"
        tr_stopping_clients="Stopping clients"
        tr_stopping_jack="Stopping JACK"
        ;;
esac
