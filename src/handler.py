from runpod.serverless.utils import rp_upload
import runpod
import os
import sys
import time
import json
import requests
import base64
import subprocess
import threading
import uuid
from pathlib import Path
from PIL import Image
import io
import shutil
import boto3
from datetime import timedelta




# Configuración
WORKSPACE_PATH = "/runpod-volume"
COMFYUI_PATH = f"{WORKSPACE_PATH}/ComfyUI"
WORKFLOW_PATH = "/app/workflow.json"
COMFYUI_URL = "http://localhost:8188"

# 🔥 NUEVO: Configuración para RunPod output. Rutas absolutas para evitar problemas con cambios de directorio
OUTPUT_DIR = Path(f"{COMFYUI_PATH}/output")           # Donde ComfyUI guarda
RP_OUTPUT_DIR = Path("/runpod-volume/output_objects")   # <- raíz del contenedor 🔥 Network volume
RP_OUTPUT_DIR.mkdir(exist_ok=True, parents=True)


TARGET_NODE = "94"          # manténlo como string. Nodo del que sacamos el vídeo en extract_outpu...

def upload_video_runpod_getobject(src: Path, job_id: str) -> str:
    """
    Upload + GetObject para generar URL de descarga directa
    """
    import boto3, os
    from botocore.exceptions import ClientError
    
    print(f"🚀 Subiendo con GetObject support...")
    
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name="EU-RO-1",
        endpoint_url="https://s3api-eu-ro-1.runpod.io"
    )
    
    bucket_name = "z41252jtk8"
    object_key = f"videos/{job_id}/{src.name}"
    
    try:
        # 1. Upload del archivo
        s3_client.upload_file(str(src), bucket_name, object_key)
        print(f"✅ Upload exitoso: {object_key}")
        
        # 2. Verificar que el objeto existe usando HeadObject
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
            print(f"✅ Objeto verificado en bucket")
        except ClientError as e:
            print(f"⚠️ Error verificando objeto: {e}")
        
        # 3. Intentar diferentes tipos de URLs
        
        # Opción A: URL presignada (puede no funcionar)
        try:
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': object_key},
                ExpiresIn=86400  # 24 horas
            )
            print(f"✅ URL presignada: {presigned_url}")
            
            # Verificar si la URL presignada es válida
            import requests
            response = requests.head(presigned_url, timeout=10)
            if response.status_code == 200:
                print(f"✅ URL presignada verificada y funcional")
                return presigned_url
            else:
                print(f"⚠️ URL presignada no funcional: {response.status_code}")
                
        except Exception as e:
            print(f"⚠️ URL presignada falló: {e}")
        
        # Opción B: URL directa del endpoint
        direct_url = f"https://s3api-eu-ro-1.runpod.io/{bucket_name}/{object_key}"
        print(f"🔄 Probando URL directa: {direct_url}")
        
        try:
            import requests
            response = requests.head(direct_url, timeout=10)
            if response.status_code == 200:
                print(f"✅ URL directa funcional")
                return direct_url
            else:
                print(f"⚠️ URL directa no funcional: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Error verificando URL directa: {e}")
        
        # Opción C: Generar comando GetObject para verificar acceso
        print(f"📋 Para verificar manualmente, usa:")
        print(f"aws s3api get-object --bucket {bucket_name} --key {object_key} --endpoint-url https://s3api-eu-ro-1.runpod.io /tmp/test-download.mp4")
        
        # Opción D: Retornar información del objeto para debugging
        return {
            "bucket": bucket_name,
            "key": object_key,
            "endpoint": "https://s3api-eu-ro-1.runpod.io",
            "direct_url": direct_url,
            "aws_cli_command": f"aws s3api get-object --bucket {bucket_name} --key {object_key} --endpoint-url https://s3api-eu-ro-1.runpod.io downloaded_video.mp4"
        }
        
    except Exception as e:
        print(f"❌ Error en proceso: {e}")
        raise


def test_runpod_getobject_access(bucket_name: str, object_key: str) -> dict:
    """
    Probar diferentes métodos de acceso a un objeto en RunPod S3
    """
    import boto3, os, requests
    
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name="EU-RO-1",
        endpoint_url="https://s3api-eu-ro-1.runpod.io"
    )
    
    results = {}
    
    # 1. HeadObject - verificar que existe
    try:
        head_response = s3_client.head_object(Bucket=bucket_name, Key=object_key)
        results["head_object"] = "✅ SUCCESS"
        results["content_length"] = head_response.get('ContentLength', 'Unknown')
        results["content_type"] = head_response.get('ContentType', 'Unknown')
    except Exception as e:
        results["head_object"] = f"❌ FAILED: {e}"
    
    # 2. Generate presigned URL
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key},
            ExpiresIn=3600
        )
        results["presigned_url"] = presigned_url
        
        # Probar la URL presignada
        response = requests.head(presigned_url, timeout=5)
        results["presigned_url_test"] = f"✅ Status: {response.status_code}"
        
    except Exception as e:
        results["presigned_url"] = f"❌ FAILED: {e}"
    
    # 3. URL directa
    direct_url = f"https://s3api-eu-ro-1.runpod.io/{bucket_name}/{object_key}"
    try:
        response = requests.head(direct_url, timeout=5)
        results["direct_url"] = direct_url
        results["direct_url_test"] = f"Status: {response.status_code}"
    except Exception as e:
        results["direct_url_test"] = f"❌ FAILED: {e}"
    
    # 4. GetObject programático (descargar primeros bytes)
    try:
        # Descargar solo los primeros 1024 bytes para probar
        get_response = s3_client.get_object(
            Bucket=bucket_name, 
            Key=object_key,
            Range='bytes=0-1023'
        )
        results["get_object"] = "✅ SUCCESS - GetObject functional"
        results["actual_size"] = len(get_response['Body'].read())
    except Exception as e:
        results["get_object"] = f"❌ FAILED: {e}"
    
    return results

def upload_video_hybrid_complete(src: Path, job_id: str) -> str:
    """
    Función completa que prueba todos los métodos disponibles
    """
    import boto3, os, requests
    from datetime import datetime
    
    print(f"🚀 Upload completo con todas las opciones...")
    
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name="EU-RO-1",
        endpoint_url="https://s3api-eu-ro-1.runpod.io"
    )
    
    bucket_name = "z41252jtk8"
    timestamp = int(datetime.now().timestamp())
    object_key = f"videos/{job_id}/{timestamp}_{src.name}"
    
    try:
        # 1. Upload
        print(f"📤 Subiendo archivo...")
        s3_client.upload_file(str(src), bucket_name, object_key)
        print(f"✅ Upload exitoso: {object_key}")
        
        # 2. Probar todos los métodos de acceso
        print(f"🧪 Probando métodos de acceso...")
        test_results = test_runpod_getobject_access(bucket_name, object_key)
        
        # 3. Imprimir resultados
        print(f"📊 Resultados de pruebas:")
        for method, result in test_results.items():
            print(f"  {method}: {result}")
        
        # 4. Retornar la mejor opción disponible
        if "presigned_url" in test_results and test_results.get("presigned_url_test", "").startswith("✅"):
            print(f"🎯 Usando URL presignada")
            return test_results["presigned_url"]
        
        elif "direct_url" in test_results and "200" in test_results.get("direct_url_test", ""):
            print(f"🎯 Usando URL directa")
            return test_results["direct_url"]
        
        else:
            print(f"⚠️ Métodos automáticos fallaron, retornando info del objeto")
            return {
                "status": "uploaded_but_no_direct_access",
                "bucket": bucket_name,
                "key": object_key,
                "endpoint": "https://s3api-eu-ro-1.runpod.io",
                "download_command": f"aws s3api get-object --bucket {bucket_name} --key {object_key} --endpoint-url https://s3api-eu-ro-1.runpod.io downloaded_video.mp4",
                "test_results": test_results
            }
        
    except Exception as e:
        print(f"❌ Error en upload: {e}")
        raise Exception(f"Upload failed: {e}")

def debug_rp_upload_detailed():
    """Debug detallado de rp_upload"""
    try:
        print("🔍 === DEBUGGING rp_upload ===")
        
        # Mostrar funciones disponibles
        functions = [attr for attr in dir(rp_upload) if not attr.startswith('_')]
        print(f"Funciones disponibles: {functions}")
        
        # Inspeccionar upload_file_to_bucket
        if hasattr(rp_upload, 'upload_file_to_bucket'):
            import inspect
            sig = inspect.signature(rp_upload.upload_file_to_bucket)
            print(f"upload_file_to_bucket signature: {sig}")
        
        # Inspeccionar bucket_upload
        if hasattr(rp_upload, 'bucket_upload'):
            import inspect
            sig = inspect.signature(rp_upload.bucket_upload)
            print(f"bucket_upload signature: {sig}")
            
        print("🔍 === END DEBUG ===")
        
    except Exception as e:
        print(f"❌ Error en debug: {e}")



def upload_video_boto3_fixed(src: Path, job_id: str) -> str:
    """boto3 con configuración corregida como función separada"""
    from botocore.config import Config
    
    config = Config(signature_version='s3v4')
    s3_client = boto3.client(
        's3',
        region_name=REGION,
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=os.environ["BUCKET_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["BUCKET_SECRET_ACCESS_KEY"],
        config=config
    )
    
    key = f"{job_id}/{src.name}"
    
    with open(src, "rb") as fh:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=fh,
            ContentType="video/mp4"
        )
    
    return s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': BUCKET_NAME, 'Key': key},
        ExpiresIn=int(timedelta(days=7).total_seconds())
    )


def upload_video(src: Path, job_id: str) -> str:
    from botocore.config import Config
    
    # Configuración específica para RunPod S3
    config = Config(
        signature_version='s3v4',
        region_name=REGION,
        retries={'max_attempts': 4, 'mode': 'adaptive'}
    )
    
    # Recrear el cliente S3 con la configuración correcta
    s3_client = boto3.client(
        "s3",
        region_name=REGION,
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=os.environ["BUCKET_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["BUCKET_SECRET_ACCESS_KEY"],
        config=config  # ← Esta es la clave
    )
    
    key = f"{job_id}/{src.name}"
    
    # 1. Subida del archivo
    with open(src, "rb") as fh:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=fh,
            ContentType="video/mp4"
        )
    
    # 2. Generar URL presignada con la configuración correcta
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': key
            },
            ExpiresIn=int(timedelta(days=7).total_seconds())
        )
        
        print(f"✅ URL presignada generada: {presigned_url}")
        return presigned_url
        
    except Exception as e:
        print(f"❌ Error generando URL presignada: {e}")
        raise Exception(f"Failed to generate presigned URL: {e}")

def save_base64_image(base64_string, filename):
    """Guardar imagen base64 en el sistema de archivos con procesamiento PIL"""
    try:
        # Remover el prefijo data:image si existe
        if ',' in base64_string:
            base64_string = base64_string.split(',')[1]

        # Añadir padding si es necesario para evitar el error "Incorrect padding"
        missing_padding = len(base64_string) % 4
        if missing_padding:
            base64_string += '=' * (4 - missing_padding)

        # Decodificar base64
        image_data = base64.b64decode(base64_string)
                
        # Cargar imagen desde bytes
        image = Image.open(io.BytesIO(image_data))
        
        # Manejar diferentes modos de color correctamente
        if image.mode == 'RGBA':
            # Crear fondo blanco para transparencias
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])  # Alpha channel
            image = background
        elif image.mode == 'P':
            # Paleta de colores
            image = image.convert('RGB')
        elif image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        
        # Crear directorio input si no existe
        input_dir = f"{COMFYUI_PATH}/input"
        os.makedirs(input_dir, exist_ok=True)
        
        # Guardar imagen con máxima calidad
        image_path = f"{input_dir}/{filename}"
        image.save(image_path, 'PNG', optimize=False, compress_level=0)
        
        print(f"✅ Image saved: {image_path} (Mode: {image.mode}, Size: {image.size})")
        return filename
        
    except Exception as e:
        print(f"❌ Error saving image: {e}")
        raise Exception(f"Failed to save input image: {e}")


def download_image_from_url(image_url):
    """Descargar imagen desde URL"""
    try:
        
        print(f"📥 Downloading image from: {image_url}")
        
        # Descargar imagen
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        # Procesar con PIL
        image = Image.open(io.BytesIO(response.content))
        
        # Manejar diferentes modos de color
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode == 'P':
            image = image.convert('RGB')
        elif image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        
        # Guardar
        input_dir = f"{COMFYUI_PATH}/input"
        os.makedirs(input_dir, exist_ok=True)
        
        timestamp = int(time.time() * 1000000)
        filename = f"input_{timestamp}.png"
        image_path = f"{input_dir}/{filename}"
        
        image.save(image_path, 'PNG', optimize=False, compress_level=0)
        
        print(f"✅ Image downloaded and saved: {image_path} (Mode: {image.mode}, Size: {image.size})")
        return filename  # ✅ Devolver solo filename para consistencia
        
    except Exception as e:
        print(f"❌ Error downloading image: {e}")
        raise Exception(f"Failed to download image: {e}")

def process_image_input(image_input):
    """Procesar imagen desde cualquier formato"""
    try:
        if isinstance(image_input, str):
            if image_input.startswith(("http://", "https://")):
                # URL
                print("🔗 Processing image from URL")
                return download_image_from_url(image_input)
            elif image_input.startswith("data:image") or len(image_input) > 100:
                # Base64
                print("📄 Processing image from Base64")
                timestamp = int(time.time() * 1000000)
                filename = f"input_{timestamp}.png"
                return save_base64_image(image_input, filename)
            else:
                raise ValueError(f"Invalid image string format: {image_input[:50]}...")
        else:
            raise ValueError(f"Unknown image input format: {type(image_input)}")
            
    except Exception as e:
        print(f"❌ Error processing image: {e}")
        raise Exception(f"Failed to process image: {e}")


def modify_workflow(workflow: dict,
                    image_filename: str,
                    prompt: str,
                    negative_prompt: str,
                    width: int = 832,
                    height: int = 480) -> dict:
    """
    Modifica el workflow con los parámetros del usuario
    """
    import time
    
    # Generar seed único
    unique_seed = int(time.time() * 1000000) % 2147483647  # Más variación
    print(f"🎲 Generated unique seed: {unique_seed}")
    
    # Crear una copia del workflow para no modificar el original
    modified_workflow = workflow.copy()
    
    # NODO 294: LoadImage - Actualizar imagen de entrada
    if "294" in modified_workflow:
        if "inputs" in modified_workflow["294"]:
            modified_workflow["294"]["inputs"]["image"] = image_filename
            print(f"✅ Updated LoadImage (294) with image: {image_filename}")
        else:
            print(f"❌ Node 294 missing inputs section")
    else:
        print(f"❌ Node 294 (LoadImage) not found in workflow")
    
    # NODO 243: Prompt positivo
    if "243" in modified_workflow:
        if "inputs" in modified_workflow["243"]:
            modified_workflow["243"]["inputs"]["text"] = prompt
            print(f"✅ Updated positive prompt (243): {prompt[:50]}...")
        else:
            print(f"❌ Node 243 missing inputs section")
    else:
        print(f"❌ Node 243 (positive prompt) not found in workflow")
    
    # NODO 244: Prompt negativo
    if "244" in modified_workflow:
        if "inputs" in modified_workflow["244"]:
            modified_workflow["244"]["inputs"]["text"] = negative_prompt
            print(f"✅ Updated negative prompt (244): {negative_prompt[:50]}...")
        else:
            print(f"❌ Node 244 missing inputs section")
    else:
        print(f"❌ Node 244 (negative prompt) not found in workflow")
    
    # NODO 259: KSampler - Actualizar seed
    if "259" in modified_workflow:
        if "inputs" in modified_workflow["259"]:
            modified_workflow["259"]["inputs"]["seed"] = unique_seed
            print(f"✅ Updated KSampler (259) seed: {unique_seed}")
        else:
            print(f"❌ Node 259 missing inputs section")
    else:
        print(f"❌ Node 259 (KSampler) not found in workflow")

    # NODO 236: WanImageToVideo - width y height
    if "236" in modified_workflow and "inputs" in modified_workflow["236"]:
        modified_workflow["236"]["inputs"]["width"] = width
        modified_workflow["236"]["inputs"]["height"] = height
        print(f"✅ Updated WanImageToVideo dimensions: {width}x{height}")
    
    # Verificar que los cambios se aplicaron
    print("🔍 Verification:")
    if "294" in modified_workflow and "inputs" in modified_workflow["294"]:
        print(f"  - Image: {modified_workflow['294']['inputs'].get('image', 'NOT SET')}")
    if "243" in modified_workflow and "inputs" in modified_workflow["243"]:
        print(f"  - Positive: {modified_workflow['243']['inputs'].get('text', 'NOT SET')[:30]}...")
    if "244" in modified_workflow and "inputs" in modified_workflow["244"]:
        print(f"  - Negative: {modified_workflow['244']['inputs'].get('text', 'NOT SET')[:30]}...")
    if "259" in modified_workflow and "inputs" in modified_workflow["259"]:
        print(f"  - Seed: {modified_workflow['259']['inputs'].get('seed', 'NOT SET')}")
    
    return modified_workflow


# FUNCIÓN DE DEBUG
def debug_workflow_connections(workflow: dict):
    """Debug para entender las conexiones actuales del workflow"""
    print("🔍 === WORKFLOW DEBUG ===")
    
    # Verificar nodos críticos
    critical_nodes = ["231", "232", "233", "302", "243", "244", "236", "290"]
    
    for node_id in critical_nodes:
        if node_id in workflow:
            node = workflow[node_id]
            class_type = node.get("class_type", "Unknown")
            inputs = node.get("inputs", {})
            print(f"🔍 Node {node_id} ({class_type}):")
            for input_name, input_value in inputs.items():
                print(f"    {input_name}: {input_value}")
        else:
            print(f"❌ Node {node_id} NOT FOUND in workflow")
    
    # Verificar específicamente los nodos Anything Everywhere
    anything_everywhere_nodes = ["280", "281", "282"]
    print("\n🔍 === ANYTHING EVERYWHERE NODES ===")
    for node_id in anything_everywhere_nodes:
        if node_id in workflow:
            node = workflow[node_id]
            print(f"🔍 Node {node_id}: {node}")
        else:
            print(f"❌ Anything Everywhere node {node_id} NOT FOUND")
    
    print("🔍 === END DEBUG ===\n")


def execute_workflow(job_id, workflow):
    """Ejecutar workflow en ComfyUI y esperar resultado"""
    try:
        # Generar ID único para este prompt
        prompt_id = str(uuid.uuid4())
        
        # Preparar payload para ComfyUI API
        payload = {
            "prompt": workflow,
            "client_id": prompt_id
        }
        
        print(f"🚀 Sending workflow to ComfyUI with ID: {prompt_id}")
        
        # Enviar workflow a ComfyUI
        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload)
        response.raise_for_status()
        
        result = response.json()
        prompt_id = result["prompt_id"]
        print(f"✅ Workflow submitted successfully, prompt_id: {prompt_id}")
        
        # Polling para esperar a que termine
        print("⏳ Waiting for workflow execution...")
        max_wait = 900  # antes era 5 minutos máximo ahora es 15
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            # Verificar estado
            history_response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}")
            
            if history_response.status_code == 200:
                history = history_response.json()
                
                if prompt_id in history:
                    execution_data = history[prompt_id]
                    
                    # Verificar si terminó
                    if "outputs" in execution_data:
                        print("✅ Workflow execution completed!")
                        # Pasa el job_id a extract_output_files
                        return extract_output_files(job_id, execution_data["outputs"]) # <-- AÑADE job_id
                    
                    # Verificar si hay error
                    elif "status" in execution_data:
                        status = execution_data["status"]
                        if status.get("status_str") == "error":
                            error_msg = status.get("messages", ["Unknown error"])
                            raise Exception(f"Workflow execution failed: {error_msg}")
            
            # Esperar antes del siguiente check
            time.sleep(5)
            
            # Log de progreso cada 30 segundos
            if int(time.time() - start_time) % 30 == 0:
                elapsed = int(time.time() - start_time)
                print(f"⏳ Still waiting... ({elapsed}s elapsed)")
        
        raise Exception("Workflow execution timeout after 15 minutes")
        
    except Exception as e:
        print(f"❌ Error executing workflow: {e}")
        raise Exception(f"Failed to execute workflow: {e}")



def extract_output_files(job_id, outputs): # <-- Acepta job_id
    """Usar rp_upload para obtener URLs descargables y devolver la URL del video."""
    # Debug de rp_upload al inicio
    debug_rp_upload_detailed()
    
    for node_id, node_output in outputs.items():
        if str(node_id) != TARGET_NODE:  # TARGET_NODE es '94'
            continue

        # La salida puede estar en 'videos' o 'gifs', sé flexible
        for key in ("videos", "gifs"):
            if key not in node_output:
                continue

            video_info = node_output[key][0]
            # La ruta completa del archivo generado en el contenedor
            src = Path(video_info["fullpath"])

            if not src.exists():
                raise FileNotFoundError(f"El archivo de video no se encontró en la ruta: {src}")

            # Sube el archivo a RunPod y obtén la URL segura
            try:
                print(f"🚀 Subiendo {src.name} al bucket con el job_id: {job_id}")
                
                # --- Usando la llamada a la función 100% correcta ---
                video_url = upload_video_hybrid(src, job_id)
                # ----------------------------------------------------
                
                print(f"✅ Video subido exitosamente. URL: {video_url}")
                
                return {
                    "type": "video",
                    "url": video_url,
                    "filename": src.name,
                    "original_path": str(src),
                    "file_size": f"{round(src.stat().st_size / 1_048_576, 2)} MB",
                    "node_id": TARGET_NODE
                }
                
            except Exception as e:
                print(f"❌ Error al subir el video con rp_upload: {e}")
                # Si la subida falla, es un error crítico
                raise RuntimeError(f"No se pudo subir el archivo de video: {e}")

    # Si no se encuentra el nodo de salida, lanza un error
    raise RuntimeError(f"No se encontró ninguna salida de video en el nodo esperado ({TARGET_NODE})")


def file_to_base64(file_path):
    """Convertir archivo a base64"""
    try:
        with open(file_path, 'rb') as f:
            file_data = f.read()
            base64_data = base64.b64encode(file_data).decode('utf-8')
            return base64_data
    except Exception as e:
        print(f"❌ Error converting file to base64: {e}")
        return None

def generate_video(job_id, input_image, prompt, negative_prompt="", width=832, height=480):
    """Generar video usando el workflow completo"""
    try:
        print("🎬 Starting video generation...")
        
       # 1. Procesar imagen de entrada (híbrido)
        saved_filename = process_image_input(input_image)
        
        # 2. Cargar y modificar workflow
        print("📝 Loading and modifying workflow...")
        with open(WORKFLOW_PATH, 'r') as f:
            workflow = json.load(f)

        # 🔥 NUEVO: Debug inicial
        print("🔍 BEFORE modifications:")
     #   debug_workflow_connections(workflow)
        
        modified_workflow = modify_workflow(workflow, saved_filename, prompt, negative_prompt, width, height)

        # 🔥 NUEVO: Debug después de modify_workflow
        print("🔍 AFTER modify_workflow:")
      #  debug_workflow_connections(modified_workflow)

                  
        # 3. Ejecutar workflow y obtener el diccionario con la URL
        output_data = execute_workflow(job_id, modified_workflow) # <-- AÑADE job_id
        
        if not output_data or "url" not in output_data:
            raise Exception("No se generó la URL del video de salida")
        
        print(f"✅ Generación de video completada. URL: {output_data['url']}")
        
        # 4. Devuelve el resultado incluyendo el diccionario completo de salida
        return {
            "status": "success",
            "output": output_data  # Devuelve directamente el objeto con la URL
        }
        
    except Exception as e:
        print(f"❌ La generación de video falló: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

def get_file_size(file_path):
    """Obtener tamaño del archivo en MB"""
    try:
        size_bytes = os.path.getsize(file_path)
        size_mb = round(size_bytes / (1024 * 1024), 2)
        return f"{size_mb} MB"
    except:
        return "Unknown"


def check_models():
    """Verificar que los modelos estén disponibles en el network volume"""
    required_models = {
        "diffusion_models": ["wan2.1_i2v_480p_14B_bf16.safetensors"],
        "text_encoders": ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"],
        "vae": ["wan_2.1_vae.safetensors"],
        "clip_vision": ["clip_vision_h.safetensors"],
        "upscale_models": ["4xLSDIR.pth"]
    }
    
    for model_type, models in required_models.items():
        model_path = f"{COMFYUI_PATH}/models/{model_type}"
        if not os.path.exists(model_path):
            raise Exception(f"Model directory not found: {model_path}")
        
        for model in models:
            model_file = f"{model_path}/{model}"
            if not os.path.exists(model_file):
                raise Exception(f"Required model not found: {model_file}")
    
    print("✅ All required models found!")
    return True

def start_comfyui():
    """Iniciar ComfyUI server o verificar si ya está ejecutándose"""
    # 🔥 NUEVO: Verificar si ComfyUI ya está ejecutándose
    try:
        response = requests.get(f"{COMFYUI_URL}/history", timeout=5)
        if response.status_code == 200:
            print("✅ ComfyUI already running! Reusing existing instance.")
            return True
    except Exception:
        print("🔧 ComfyUI not running, starting new instance...")
        
     # 🔥 SOLUCIÓN ELEGANTE: Verificar/crear symlink solo si no existe
    symlink_path = "/ComfyUI"
    if not (os.path.exists(symlink_path) or os.path.islink(symlink_path)):
        os.symlink(COMFYUI_PATH, symlink_path)
        print(f"🔗 Symlink creado: {symlink_path} → {COMFYUI_PATH}")
    else:
        print(f"ℹ️ {symlink_path} ya existe: se reutiliza (link o directorio).")
    
    print(f"📂 Changing directory to: {COMFYUI_PATH}")
    os.chdir(COMFYUI_PATH)
    
    # Verificar que main.py existe
    if not os.path.exists("main.py"):
        raise Exception(f"❌ main.py not found in {COMFYUI_PATH}")
    
    print("🔧 Starting ComfyUI process...")
    cmd = [
        "python", "main.py", 
        "--listen", "0.0.0.0",
        "--port", "8188"
    ]
    
    print(f"🚀 Command: {' '.join(cmd)}")
    
    # Iniciar ComfyUI con logs visibles
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Mostrar logs en tiempo real
    def show_logs():
        for line in process.stdout:
            print(f"ComfyUI: {line.strip()}")
    
    thread = threading.Thread(target=show_logs, daemon=True)
    thread.start()
    
    # Esperar a que ComfyUI esté listo
    print("⏳ Waiting for ComfyUI to be ready...")
    for i in range(300):  # 5 minutos
        try:
            response = requests.get(f"{COMFYUI_URL}/history", timeout=5)
            if response.status_code == 200:
                print("✅ ComfyUI is ready!")
                return True
        except Exception as e:
            if i % 30 == 0:  # Log cada 30 segundos
                print(f"⏳ Still waiting... ({i//60}m {i%60}s) - {e}")
        time.sleep(1)
    
    print("❌ ComfyUI logs:")
    if process.poll() is not None:
        print(f"Process exited with code: {process.returncode}")
    
    raise Exception("❌ ComfyUI failed to start within 5 minutes")

def handler(event):
    """Handler principal de RunPod"""
    try:
        print("🚀 Starting WAN 2.1 I2V serverless handler...")
        
        # Verificar modelos
        print("🔍 Checking models...")
        check_models()
        
        # Iniciar ComfyUI
        print("⚡ Starting ComfyUI...")
        start_comfyui()
        
        # Obtener inputs
        job_input = event.get("input", {})
        job_id = event.get("id") # <-- AÑADE ESTA LÍNEA
        
        if not job_input:
            return { 
                "message": "No input provided"
            }
        
        # Generar video
        result = generate_video(
            job_id, # <-- AÑADE ESTE ARGUMENTO
            job_input.get("image", ""),
            job_input.get("prompt", ""),
            job_input.get("negative_prompt", ""),
            job_input.get("width", 832),      # Valor por defecto
            job_input.get("height", 480)      # Valor por defecto
        )
        
        return result
        
    except Exception as e:
        return {
            "message": str(e)
        }

print("🚀 Starting RunPod Serverless handler...")
runpod.serverless.start({"handler": handler})
