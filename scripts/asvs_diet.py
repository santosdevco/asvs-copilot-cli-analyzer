import argparse
import glob
import json
import os

def trim_example(text):
    """
    Recorta el texto eliminando explicaciones innecesarias y ejemplos.
    Busca patrones específicos y corta la cadena, asegurando que termine en punto.
    """
    # Frases clave donde OWASP empieza a dar ejemplos o explicaciones largas
    split_phrases = [" For example", " for example", " For instance", " for instance"]
    
    for phrase in split_phrases:
        if phrase in text:
            # Cortamos el texto justo antes de la frase
            text = text.split(phrase)[0].strip()
            
            # Si al cortar quedó una coma colgando (ej. "hacer algo, for example..."), la quitamos
            if text.endswith(','):
                text = text[:-1]
                
            # Restauramos el punto final para que sea gramaticalmente correcto
            if not text.endswith('.'):
                text += '.'
            break # Si ya cortamos con uno, terminamos
            
    return text

def process_asvs_file(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if "chapter" in data:
        # 1. Eliminar narrativa global del capítulo (Ahorro MASIVO de tokens)
        if "control_objective" in data["chapter"]:
            del data["chapter"]["control_objective"]
            
        if "sections" in data["chapter"]:
            for section in data["chapter"]["sections"]:
                # 2. Eliminar narrativa explicativa de la sección
                if "description" in section:
                    del section["description"]
                    
                # 3. Aplicar la dieta a cada requerimiento individual
                if "requirements" in section:
                    for req in section["requirements"]:
                        if "description" in req:
                            req["description"] = trim_example(req["description"])
                            
    # Asegurar que la carpeta de destino exista
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Guardar el JSON minificado (indent=2 para que siga siendo legible, 
    # pero puedes poner None si quieres minificación de una sola línea)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Aplica la 'Dieta ASVS' a los archivos JSON")
    parser.add_argument("--input-folder", required=True, help="Carpeta con los JSON originales del ASVS")
    parser.add_argument("--output-folder", required=True, help="Carpeta destino para los JSON optimizados")
    
    args = parser.parse_args()
    
    input_files = glob.glob(os.path.join(args.input_folder, "*.json"))
    
    if not input_files:
        print(f"⚠️ No se encontraron archivos JSON en la carpeta: {args.input_folder}")
        return
        
    print(f"Encontrados {len(input_files)} archivos ASVS. Iniciando la purga de tokens...\n")
    
    for file in input_files:
        filename = os.path.basename(file)
        output_file = os.path.join(args.output_folder, filename)
        process_asvs_file(file, output_file)
        print(f"✅ Optimizado: {filename}")
        
    print("\n🚀 ¡Dieta ASVS aplicada exitosamente! Tus prompts ahora son mucho más ligeros.")

if __name__ == "__main__":
    main()