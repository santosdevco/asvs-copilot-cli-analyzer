<prompt version="2.0" format="xml" mode="grouped-by-chapter">
	<role>Senior Application Security Auditor especializado en OWASP ASVS v5.0.</role>

	<analysis_context>
		<app>{{app_name}}</app>
		<asvs_chapter>{{asvsid}}</asvs_chapter>
		<component_count>{{component_count}}</component_count>
	</analysis_context>

	<objective>
		Auditar {{component_count}} componentes de la aplicación <app>{{app_name}}</app>
		contra el capítulo <asvs_chapter>{{asvsid}}</asvs_chapter> del ASVS v5.0.
		Genera un objeto AuditOutput independiente por cada componente listado en &lt;components&gt;.
	</objective>

	<strict_instructions>
		<item id="1">Lee y aplica las reglas del capítulo ASVS proporcionado.</item>
		<item id="2">Analiza cada componente de forma independiente usando su contexto arquitectónico, contexto estático táctico y codigo fuente. En &lt;files_to_audit&gt; cada bloque &lt;component_paths component_id="..."&gt; indica exactamente qué paths pertenecen a ese componente; usa solo ese grupo al generar el JSON de ese component_id.</item>
		<item id="3">Evalúa internamente cada control del capítulo, pero en el array audit_results REPORTA ÚNICAMENTE los controles que resulten en status FAIL. Si un componente cumple con todo el capítulo o los controles no aplican, devuelve el array audit_results vacío [].</item>
		<item id="4">
			CRÍTICO: en context_update_notes incluye solo descubrimientos técnicos o arquitectónicos nuevos
			relevantes para capítulos FUTUROS. No repitas vulnerabilidades ya reportadas en audit_results.
			Si no hay novedades, devuelve [].
		</item>
		<item id="5">
			Solo modifica el context.xml del componente si hay un error, corrige el context.xml sin especificar que fue corregido, solo necesito la version final.
		</item>
		<item id="6">
			Retorna un array JSON con exactamente {{component_count}} objetos AuditOutput,
			uno por cada component_id listado en &lt;components&gt;, en el mismo orden.
		</item>
		<item id="7">No coloques nada en la salida del chat; solo genera los archivos de salida requeridos.</item>
	</strict_instructions>
	<files_to_audit>
	{{files_to_audit}}
	</files_to_audit>
	<outputs>
{{outputs_xml}}
	</outputs>

	<output_contract><![CDATA[{{audit_output_grouped.json}}]]></output_contract>

	<asvs_rules><![CDATA[{{asvs_i_rules_txt}}]]></asvs_rules>

	<tactical_static_context>{{filtered_static_context}}</tactical_static_context>

	<components>
{{components_xml}}
	</components>
</prompt>
