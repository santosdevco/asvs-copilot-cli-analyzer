<prompt version="2.0" format="xml">
	<role>
		Principal Security Architect y Experto en OWASP ASVS v5.0.
	</role>

	<objective>
		Analizar el contexto estático completo de una aplicación y agrupar los archivos en componentes
		de alto nivel para auditoría posterior.
	</objective>
	<source_dir_path>
		{{source_dir_path}}
	</source_dir_path>

	<strict_instructions>
		<item id="1">
			Analiza el CONTEXTO ESTÁTICO DE LA APLICACIÓN y complementa leyendo rutas de código
			referenciadas en el static context. Confirma que estas leyendo las rutas correctas. Agrupa archivos en componentes lógicos de alto nivel
			(ej. Módulo de Autenticación, Procesamiento de Pagos, Frontend UI).
			Solo puedes leer lo que esta adentro de source_dir_path
		</item>
		<item id="2">
			Asigna a cada componente las etiquetas correctas en asset_tags usando solo el catálogo permitido.
		</item>
		<item id="3">
			Determina el nivel de riesgo del componente usando únicamente: CRITICAL, HIGH, MEDIUM, LOW.
		</item>
		<item id="4">
			Redacta el context.xml describiendo ÚNICAMENTE: arquitectura, flujos de datos, fronteras de
			confianza, dependencias externas y reglas de negocio. NO emitas juicios sobre vulnerabilidades,
			hallazgos de seguridad ni recomendaciones de remediación.
		</item>
		<item id="5">
			CRÍTICO: Si el componente ya tiene un context.xml existente NO lo puedes leer, renombra el anterior con la fecha de hoy y  crear el context.xml.
		</item>
		<item id="6">
			El context.xml NO debe contener: vulnerabilidades, hallazgos de auditoría, issues de seguridad,
			ni menciones a ASVS checks. Esa información va en los archivos de análisis por capítulo (V1.xml, V2.xml, etc.).
		</item>
		<item id="7">
			El index.json contiene SOLO: component_id, component_name, risk_level, asset_tags, files_to_audit,core_paths.
			NO incluyas initial_semantic_context ni ningún otro campo adicional. El contexto arquitectónico
			va exclusivamente en context.xml.
		</item>
		<item id="8">
			Debes definir todos los component_key necesarios.
		</item>
		<item id="9">
			No coloques nada en la salida del chat; solo genera/modifica los archivos de salida requeridos.
		</item>
		<item id="10">
			Sigue estrictamente los contratos de salida provistos.
		</item>
		<item id="11">
			core_paths, es la lista de archivos generales que siempre deben tenerse en cuenta para cualquier componente.
		</item>
		<item id="12">
			CRÍTICO - JERARQUÍA DE ARCHIVOS: Las rutas en &lt;outputs&gt; son RELATIVAS a la raíz del proyecto.
			NO anides las carpetas de salida dentro de 'analysis-repos'. 
			La estructura correcta debe ser: ROOT/outputs/..., NO ROOT/analysis-repos/app/outputs/...
		</item>
	</strict_instructions>

	<allowed_asset_tags><![CDATA[
{{asset_tags}}
	]]></allowed_asset_tags>

	<outputs>
		<file required="true">outputs/{{app_name}}/components/index.json</file>
		<file required="true" repeat="for_each_component" condition="new_or_correction_needed">outputs/{{app_name}}/components/{component_key}/context.yml</file>
	</outputs>

	<output_contracts>
		<index_json><![CDATA[
{{component_json_format}}
		]]></index_json>
		<component_context_yml description="Factual architectural context only — NO vulnerability judgments"><![CDATA[
{{component_context_format}}
		]]></component_context_yml>
	</output_contracts>

	<application_static_context>
{{full_static_context}}
	</application_static_context>
</prompt>