from __future__ import annotations

import re
import time

try:
    import pyvjoy
except ImportError:
    pyvjoy = None

from EDlogger import logger
from EDShipControl import scale

"""
File: vJoy_input.py

Description:
    Gestion centralisée de la simulation de joystick via vJoy (https://github.com/jshafer817/pyvjoy).

Pré-requis:
    - Driver vJoy installé (https://sourceforge.net/projects/vjoystick/) avec les devices configurés
      (axes + boutons nécessaires) via "Configure vJoy". Ce projet utilise 2 devices vJoy, 16 boutons
      chacun.
    - pip install pyvjoy

Format du code de simulation:
    'Joy{DeviceIndex}_{NomAxeOuBouton}', ex: 'Joy0_XAxis', 'Joy1_RZAxis', 'Joy0_4'
    DeviceIndex est 0-based (comme dans Joy_SCANCODE de directinput.py). Il est converti en interne
    vers l'ID vJoy 1-based (Device 1, Device 2, ...).

Note:
    A paramétrer sur Elite: Options > Contrôles > "Alternative Flight Control" doit être assigné au(x)
    axe(s) du device vJoy correspondant (rebind à faire une seule fois dans le jeu).
    Pour visualiser les valeurs envoyées en direct: Win+R -> joy.cpl -> périphérique vJoy -> Propriétés -> Tester.
"""


# ----------------------------------------------------------------------------
# Constantes vJoy
# ----------------------------------------------------------------------------

VJOY_AXIS_MIN = 0x0001   # Valeur mini valide d'un axe vJoy
VJOY_AXIS_MID = 0x4000   # Point mort (centre) d'un axe vJoy
VJOY_AXIS_MAX = 0x8000   # Valeur maxi valide d'un axe vJoy

# Nombre de boutons configurés par device vJoy (2 devices, 16 boutons chacun).
_VJOY_BUTTON_COUNT = 16

# Table de correspondance nom logique d'axe -> constante HID pyvjoy.
# Remplie dynamiquement seulement si pyvjoy est disponible.
_AXIS_HID_MAP: dict[str, int] = {}
if pyvjoy is not None:
    _AXIS_HID_MAP = {
        "XAxis":   pyvjoy.HID_USAGE_X,
        "YAxis":   pyvjoy.HID_USAGE_Y,
        "ZAxis":   pyvjoy.HID_USAGE_Z,
        "RXAxis":  pyvjoy.HID_USAGE_RX,
        "RYAxis":  pyvjoy.HID_USAGE_RY,
        "RZAxis":  pyvjoy.HID_USAGE_RZ,
        "Slider0": pyvjoy.HID_USAGE_SL0,
        "Slider1": pyvjoy.HID_USAGE_SL1,
    }

# Cache des devices vJoy déjà ouverts, indexés par DeviceIndex ("0", "1", ...)
_vjoy_devices: dict[str, "pyvjoy.VJoyDevice"] = {}


# ----------------------------------------------------------------------------
# Gestion des devices vJoy
# ----------------------------------------------------------------------------

def _get_vjoy_device(device_index: str) -> "pyvjoy.VJoyDevice":
    """ Ouvre (ou récupère depuis le cache) le device vJoy correspondant au DeviceIndex.
    @param device_index: Index 0-based du device (ex: '0' pour le premier vJoy configuré, '1' pour le second).
    @return: L'instance pyvjoy.VJoyDevice correspondante.
    """
    if pyvjoy is None:
        raise RuntimeError(
            "pyvjoy n'est pas installé. Faites 'pip install pyvjoy' et installez le driver vJoy."
        )

    device = _vjoy_devices.get(device_index)
    if device is None:
        # pyvjoy/vJoy indexe les devices à partir de 1 (Device 1, Device 2, ...)
        vjoy_id = int(device_index) + 1
        device = pyvjoy.VJoyDevice(vjoy_id)
        _vjoy_devices[device_index] = device
        logger.info(f"vJoy_input: device vJoy {vjoy_id} (DeviceIndex {device_index}) ouvert.")
    return device


def PushJoy(joy_code: str, value: float):
    """ Simule un axe ou un bouton de joystick via un device vJoy virtuel.
    @param joy_code: Code au format 'Joy{DeviceIndex}_{NomBoutonOuAxe}', ex: 'Joy0_XAxis' ou 'Joy1_4'.
    @param value: Pour un axe: 1.0 = valeur max, 0.0 = point mort, -1.0 = valeur max opposée.
                  Pour un bouton: != 0 = pressé, 0 = relâché.
    @return: N/A
    """
    print("PushJoy: ", joy_code, value)
    match = re.match(r'^Joy(\d+)_(.+)$', joy_code)
    if not match:
        raise ValueError(f"Format de joy_code invalide : '{joy_code}'. Attendu: 'Joy<index>_<nom>'.")

    device_index, name = match.group(1), match.group(2)
    device = _get_vjoy_device(device_index)

    if name in _AXIS_HID_MAP:
        # --- C'est un axe ---
        axis = _AXIS_HID_MAP[name]
        clamped = max(min(float(value), 1.0), -1.0)
        axis_value = int(round(scale(clamped, -1.0, 1.0, VJOY_AXIS_MIN, VJOY_AXIS_MAX, clamp=True)))
        device.set_axis(axis, axis_value)
        logger.debug(f"PushJoy: {joy_code} -> axe {name} = {axis_value} (valeur demandée {value})")
    else:
        # --- C'est un bouton (nom numérique, ex: '1', '2', ... '16') ---
        try:
            btn_number = int(name)
        except ValueError:
            raise ValueError(f"Élément de joystick non reconnu '{name}' dans le code '{joy_code}'.")
        state = 1 if value != 0 else 0
        device.set_button(btn_number, state)
        logger.debug(f"PushJoy: {joy_code} -> bouton {btn_number} = {state}")


def release_all_vjoy():
    """Remet à zéro tous les axes et boutons des 2 devices vJoy configurés
    en utilisant PushJoy().

    @return: N/A
    """
    for device_index in ("0", "1"):
        # Axes
        for axis_name in _AXIS_HID_MAP:
            try:
                PushJoy(f"Joy{device_index}_{axis_name}", 0.0)
            except Exception as e:
                logger.debug(
                    f"vJoy_input: impossible de remettre l'axe {axis_name} du device {device_index} au neutre: {e}"
                )

        # Boutons
        for btn_number in range(1, _VJOY_BUTTON_COUNT + 1):
            try:
                PushJoy(f"Joy{device_index}_{btn_number}", 0.0)
            except Exception as e:
                logger.debug(
                    f"vJoy_input: impossible de relâcher le bouton {btn_number} du device {device_index}: {e}"
                )

        logger.info(f"vJoy_input: device DeviceIndex {device_index} réinitialisé.")


# ----------------------------------------------------------------------------
# Test manuel
# ----------------------------------------------------------------------------

def main():
    print("Test vJoy démarré (2 devices, 16 boutons chacun). CTRL+C pour arrêter.")
    try:
        PushJoy('Joy1_XAxis', -1.0)   # Pleine gauche sur le device 1
        time.sleep(2)
        PushJoy('Joy1_XAxis', 0.0)    # Neutre
        time.sleep(2)
        PushJoy('Joy1_YAxis', -1.0)   # Pleine Bas sur le device 1
        time.sleep(2)
        PushJoy('Joy1_YAxis', 0.0)    # Neutre
        time.sleep(2)
        PushJoy('Joy1_RZAxis', 1.0)   # Pleine rotation sur le device 1
        time.sleep(2)
        PushJoy('Joy1_1', 1)          # Bouton 1 pressé sur le device 1
        time.sleep(0.5)
        PushJoy('Joy1_1', 0)          # Bouton 1 relâché
    finally:
        release_all_vjoy()


if __name__ == "__main__":
    #main()
    release_all_vjoy()