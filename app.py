import os
import time
import requests
import uvicorn
import threading
import json
from fastapi import FastAPI

# Configuración inicial
SOURCE_SPACE = 'littletest/Why'  # Espacio de origen
TEMP_DOWNLOAD_DIR = './temp_downloads'
TIMEOUT_BETWEEN_UPLOADS = 5  # Tiempo de espera en segundos (fijo)
GOFILE_UPLOAD_URL = 'https://upload.gofile.io/uploadFile'

# Lista para almacenar información de las subidas exitosas
successful_uploads = []

# Crear la instancia de FastAPI
app = FastAPI()

def get_file_list(space_name):
    """
    Obtener la lista de archivos desde un espacio de Hugging Face
    
    :param space_name: Nombre del espacio
    :return: Lista de archivos
    """
    url = f'https://huggingface.co/api/spaces/{space_name}'
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            # Filtrar archivos, excluyendo .gitattributes
            return [file['rfilename'] for file in data['siblings'] if not file['rfilename'].endswith('.gitattributes')]
        else:
            print(f'Error al obtener archivos: {response.status_code}')
            return []
    except Exception as e:
        print(f'Error al obtener lista de archivos: {e}')
        return []

def download_file(space_name, file_path):
    """
    Descargar un archivo de un espacio de Hugging Face
    
    :param space_name: Nombre del espacio
    :param file_path: Ruta del archivo
    :return: Ruta local del archivo descargado o None si falla
    """
    # Crear directorio de descargas si no existe
    os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)
    
    # URL de descarga
    download_url = f'https://huggingface.co/spaces/{space_name}/resolve/main/{file_path}?download=true'
    
    try:
        # Descargar el archivo
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        # Ruta local para guardar el archivo
        local_filename = os.path.join(TEMP_DOWNLOAD_DIR, os.path.basename(file_path))
        
        with open(local_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f'Descargado: {local_filename}')
        return local_filename
    except Exception as e:
        print(f'Error al descargar el archivo {file_path}: {e}')
        return None

def get_best_server():
    """
    Obtiene el mejor servidor de Gofile para subir archivos
    
    :return: Mejor servidor o None si falla
    """
    try:
        response = requests.get('https://api.gofile.io/servers')
        response.raise_for_status()
        result = response.json()
        
        if result.get('status') == 'ok':
            servers = result.get('data', {}).get('servers', [])
            if servers:
                # Encontrar el servidor con mejor puntuación
                best_server = max(servers, key=lambda x: x.get('score', 0))
                server_name = best_server.get('name')
                if server_name:
                    print(f"Usando servidor: {server_name}")
                    return server_name
        
        print("No se pudo determinar el mejor servidor, usando store1")
        return "store1"
    except Exception as e:
        print(f"Error al obtener servidor de Gofile: {e}")
        return "store1"  # Servidor de respaldo

def upload_to_gofile(local_path, file_path):
    """
    Subir un archivo a Gofile (creando nueva sesión para cada archivo)
    
    :param local_path: Ruta local del archivo
    :param file_path: Ruta original del archivo (solo para información)
    :return: Booleano indicando éxito o fallo
    """
    # Obtener el mejor servidor para la subida
    server = get_best_server()
    upload_url = f"https://{server}.gofile.io/uploadFile"
    
    try:
        # Preparar los datos para la subida (SIN folderID para crear uno nuevo cada vez)
        files = {'file': (os.path.basename(local_path), open(local_path, 'rb'))}
        
        # Establecer cabeceras para simular un navegador
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://gofile.io',
            'Referer': 'https://gofile.io/',
        }
            
        # Realizar la subida
        print(f"Subiendo archivo a {upload_url}")
        response = requests.post(upload_url, files=files, headers=headers)
        response.raise_for_status()
        
        # Procesar la respuesta
        result = response.json()
        
        if result.get('status') == 'ok':
            data = result.get('data', {})
            folder_id = data.get('parentFolder')
            download_page = data.get('downloadPage', 'No disponible')
            guest_token = data.get('guestToken', 'No disponible')
            
            # Guardar la información de la subida exitosa
            upload_info = {
                'file': os.path.basename(file_path),
                'folder_id': folder_id,
                'download_page': download_page,
                'guest_token': guest_token
            }
            successful_uploads.append(upload_info)
            
            # Guardar la información en un archivo para referencia futura
            with open('uploads_info.json', 'w') as f:
                json.dump(successful_uploads, f, indent=2)
            
            print(f"Archivo subido correctamente a Gofile: {file_path}")
            print(f"Página de descarga: {download_page}")
            print(f"ID de carpeta: {folder_id}")
            print(f"Token de invitado: {guest_token}")
            return True
        else:
            print(f"Error en la respuesta de Gofile: {result}")
            return False
    except Exception as e:
        print(f"Error al subir el archivo {file_path} a Gofile: {e}")
        return False
    finally:
        # Asegurarse de cerrar el archivo
        if 'files' in locals() and 'file' in files:
            files['file'][1].close()

def cleanup(local_path):
    """
    Eliminar archivo local después de subirlo
    
    :param local_path: Ruta del archivo local a eliminar
    """
    try:
        os.remove(local_path)
        print(f'Archivo local eliminado: {local_path}')
    except OSError as e:
        print(f'Error al eliminar el archivo local: {e}')
        
def start_uvicorn():
    """Función para iniciar el servidor Uvicorn."""
    uvicorn.run(app, host="0.0.0.0", port=7860)

@app.get("/")
async def read_root():
    return {"message": "HuggingFace to Gofile Transfer Service"}

@app.get("/uploads")
async def get_uploads():
    """Endpoint para obtener la lista de subidas exitosas"""
    return {"uploads": successful_uploads}

def main():
    """Función principal para sincronizar archivos de un Space a Gofile"""
    # Iniciar el servidor web en un hilo separado
    uvicorn_thread = threading.Thread(target=start_uvicorn)
    uvicorn_thread.daemon = True  # El hilo terminará cuando el programa principal termine
    uvicorn_thread.start()
    
    print("Iniciando transferencia de archivos desde HuggingFace a Gofile...")
    
    # Obtener lista de archivos del Space
    file_list = get_file_list(SOURCE_SPACE)
    
    if not file_list:
        print("No se encontraron archivos para transferir.")
        return
    
    print(f"Se encontraron {len(file_list)} archivos para transferir.")
    
    # Procesar cada archivo
    for index, file_path in enumerate(file_list, 1):
        try:
            print(f"\nProcesando archivo {index}/{len(file_list)}: {file_path}")
            
            # Descargar archivo
            local_path = download_file(SOURCE_SPACE, file_path)
            
            if local_path:
                # Subir el archivo (sin reintentos)
                if upload_to_gofile(local_path, file_path):
                    # Eliminar archivo local tras subida exitosa
                    cleanup(local_path)
                else:
                    print(f"No se pudo subir el archivo {file_path}")
                
                # Timeout fijo entre archivos (solo si no es el último)
                if index < len(file_list):
                    print(f"Esperando {TIMEOUT_BETWEEN_UPLOADS} segundos antes del próximo archivo...")
                    time.sleep(TIMEOUT_BETWEEN_UPLOADS)
        except Exception as e:
            print(f"Error procesando {file_path}: {e}")
    
    print("\nTransferencia completada.")
    print(f"Se subieron {len(successful_uploads)} archivos correctamente.")
    print(f"La información de las subidas está disponible en 'uploads_info.json'")
    
    # Mantener el servidor web ejecutándose
    try:
        print("\nServidor web activo en http://0.0.0.0:7860")
        print("Visita /uploads para ver la información de las subidas")
        print("Presiona Ctrl+C para salir.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Programa terminado por el usuario.")

if __name__ == '__main__':
    main()