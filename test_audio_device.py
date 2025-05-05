import sounddevice as sd
import sys # Для вывода ошибок

print("--- Проверка Host APIs ---")
try:
    print(sd.query_hostapis())
    default_api_index = sd.default.hostapi
    if default_api_index != -1: # Если есть default API
      print(f"\nИспользуемый по умолчанию Host API: {sd.query_hostapis(default_api_index)['name']}")
    else:
      print("\nНе удалось определить Host API по умолчанию.")
except Exception as e:
    print(f"Ошибка при запросе Host API: {e}", file=sys.stderr)

print("\n--- Все аудиоустройства ---")
try:
    print(sd.query_devices())
except Exception as e:
    print(f"Ошибка при запросе всех устройств: {e}", file=sys.stderr)

print("\n--- Только устройства ввода (микрофоны) ---")
try:
    print(sd.query_devices(kind='input'))
except Exception as e:
    print(f"Ошибка при запросе устройств ввода: {e}", file=sys.stderr)

# --- Попытка найти виртуальный микрофон по имени ---
# Замените имя, если вы использовали другое при создании sink_properties=device.description
# или используйте имя .monitor из вывода pactl list short sources
target_names = ['Monitor of Virtual_Mic_Output', 'virtual_mic_output.monitor']
found = False

print("\n--- Поиск виртуального микрофона по известным именам ---")
for name in target_names:
    try:
        # Ищем среди устройств ввода
        device_info = sd.query_devices(device=name, kind='input')
        print(f"\nУспешно найдено устройство ввода по имени '{name}':")
        print(device_info)
        found = True
        # Можно добавить break, если достаточно одного совпадения
    except ValueError:
        print(f"\nУстройство ввода с именем '{name}' не найдено.")
    except Exception as e:
        print(f"Ошибка при поиске устройства '{name}': {e}", file=sys.stderr)

if not found:
    print("\nВиртуальный микрофон не найден ни по одному из стандартных имен.")
