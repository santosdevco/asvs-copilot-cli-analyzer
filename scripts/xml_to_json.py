import glob
import json
import os
import re
import xml.etree.ElementTree as ET
import ast

def parse_line_range(lr_str):
    """
    Intenta convertir el string '[45, 50]' a una lista real de Python.
    Si contiene texto como '[N/A]', lo deja como string.
    """
    if not lr_str:
        return []
    try:
        return ast.literal_eval(lr_str)
    except (ValueError, SyntaxError):
        return lr_str

def process_xml_to_json(xml_filepath):
    try:
        with open(xml_filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Limpiar bloques markdown si la IA los puso (```xml ... ```)
        content = re.sub(r'^```xml\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'```\s*$', '', content)
        
        # 2. Buscar la etiqueta raíz (Soporta <audit_report> o <audit_output>)
        match = re.search(r'<(audit_report|audit_output)>.*?</\1>', content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            print(f"⚠️ Omite: No se encontró etiqueta raíz en {xml_filepath}")
            # Modo Debug: Imprime los primeros 150 caracteres para ver qué generó realmente la IA
            print(f"🔍 DEBUG (Primeros 150 chars):\n{content[:150]}...\n")
            return
        
        xml_clean = match.group(0)
        root = ET.fromstring(xml_clean)

        # 3. Mapear datos
        audit_results = []
        results_node = root.find('audit_results')
        
        if results_node is not None:
            # Soporta que los hijos se llamen <result> o <finding>
            items = results_node.findall('result')
            if not items:
                items = results_node.findall('finding')
                
            for item in items:
                audit_results.append({
                    "requirement_id": item.findtext('requirement_id', ''),
                    "status": item.findtext('status', ''),
                    "severity": item.findtext('severity', ''),
                    "vulnerability_title": item.findtext('vulnerability_title', ''),
                    "description": item.findtext('description', ''),
                    "affected_file": item.findtext('affected_file', ''),
                    "affected_function": item.findtext('affected_function', ''),
                    "line_range": parse_line_range(item.findtext('line_range', '')),
                    "remediation_hint": item.findtext('remediation_hint', '')
                })

        context_update_notes = []
        notes_node = root.find('context_update_notes')
        if notes_node is not None:
            context_update_notes = [note.text.strip() for note in notes_node.findall('note') if note.text]

        json_data = {
            "component_id": root.findtext('component_id', ''),
            "asvs_chapter": root.findtext('asvs_chapter', ''),
            "audit_results": audit_results,
            "context_update_notes": context_update_notes
        }

        # 4. Guardar archivo JSON
        json_filepath = os.path.splitext(xml_filepath)[0] + '.json'
        
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        print(f"✅ Transformado: {os.path.basename(xml_filepath)} -> {os.path.basename(json_filepath)}")

    except Exception as e:
        print(f"❌ Error crítico procesando {xml_filepath}: {str(e)}")

if __name__ == "__main__":
    target_glob = "outputs/watshelp-bancodebogota-admin/components/*/analysis/*.xml"
    xml_files = glob.glob(target_glob)
    
    if not xml_files:
        print("No se encontraron archivos XML en la ruta especificada.")
    else:
        print(f"Encontrados {len(xml_files)} archivos XML. Iniciando...\n")
        for file in xml_files:
            process_xml_to_json(file)
        print("\n🚀 Proceso completado exitosamente.")