import argparse
import glob
import json
import os
import re
import xmltodict
import yaml

def clean_xml_string(xml_str):
    """Limpia la envoltura de markdown si la IA devolvió ```xml ... ```"""
    xml_str = re.sub(r'^```xml\s*', '', xml_str, flags=re.IGNORECASE)
    xml_str = re.sub(r'```\s*$', '', xml_str)
    return xml_str.strip()

def process_file(xml_filepath, output_format):
    try:
        with open(xml_filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Limpieza de markdown
        clean_content = clean_xml_string(content)
        
        # Encontrar el bloque XML real
        match = re.search(r'<([a-zA-Z0-9_]+)[^>]*>.*?</\1>', clean_content, re.DOTALL)
        if not match:
            print(f"⚠️ Omite: No se encontró XML válido en {xml_filepath}")
            return
            
        xml_valid = match.group(0)

        # 2. La Magia de xmltodict (Convierte todo el XML a Diccionario en 1 línea)
        parsed_dict = xmltodict.parse(xml_valid)

        # 3. Guardar en el formato solicitado
        if output_format == 'json':
            out_filepath = os.path.splitext(xml_filepath)[0] + '.json'
            with open(out_filepath, 'w', encoding='utf-8') as f:
                json.dump(parsed_dict, f, ensure_ascii=False, indent=2)
            print(f"✅ Convertido: {os.path.basename(xml_filepath)} -> {os.path.basename(out_filepath)}")
            
        elif output_format in ['yaml', 'yml']:
            out_filepath = os.path.splitext(xml_filepath)[0] + '.yaml'
            with open(out_filepath, 'w', encoding='utf-8') as f:
                # default_flow_style=False fuerza a que se vea como un YAML clásico (listas hacia abajo)
                yaml.dump(parsed_dict, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            print(f"✅ Convertido: {os.path.basename(xml_filepath)} -> {os.path.basename(out_filepath)}")

    except Exception as e:
        print(f"❌ Error procesando {xml_filepath}: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Conversor XML a JSON/YAML usando xmltodict.")
    parser.add_argument(
        "--output-format", 
        choices=['json', 'yaml', 'yml'], 
        default='json', 
        help="Formato de salida deseado (default: json)."
    )
    parser.add_argument(
        "--path", 
        default="outputs/*/components/*/context.xml", 
        help="Patrón glob para buscar los archivos XML."
    )
    
    args = parser.parse_args()

    xml_files = glob.glob(args.path)
    
    if not xml_files:
        print(f"⚠️ No se encontraron archivos XML en la ruta: {args.path}")
    else:
        print(f"Encontrados {len(xml_files)} archivos XML.")
        print(f"Modo de salida: {args.output_format.upper()}\nIniciando conversión...\n")
        
        for file in xml_files:
            process_file(file, args.output_format)
            
        print("\n🚀 Proceso completado exitosamente.")