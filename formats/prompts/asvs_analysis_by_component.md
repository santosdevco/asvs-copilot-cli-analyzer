<prompt version="2.0" format="xml" mode="grouped-by-component">
	<role>Senior Application Security Auditor especializado en OWASP ASVS v5.0.</role>

	<analysis_context>
		<app>{{app_name}}</app>
		<component>{{component_key}}</component>
		<chapter_count>{{chapter_count}}</chapter_count>
	</analysis_context>

	<objective>
		Auditar el componente <component>{{component_key}}</component> de la aplicación <app>{{app_name}}</app>
		contra {{chapter_count}} capítulos ASVS v5.0 listados en &lt;chapters&gt;.
		Genera un objeto AuditOutput independiente por cada capítulo.
	</objective>

	<strict_instructions>
		<item id="1">Analiza el componente contra cada capítulo ASVS listado en &lt;chapters&gt; por separado.</item>
		<item id="2">Usa el contexto arquitectónico del componente y el contexto estático táctico para encontrar evidencias.</item>
		<item id="3">Evalúa internamente cada control del capítulo, pero en el array audit_results REPORTA ÚNICAMENTE los controles que resulten en status FAIL. Si un componente cumple con todo el capítulo o los controles no aplican, devuelve el array audit_results vacío []</item>
		<item id="4">
			CRÍTICO: en context_update_notes incluye solo descubrimientos técnicos nuevos por capítulo
			relevantes para otros capítulos. No repitas vulnerabilidades ya reportadas. Si no hay novedades, devuelve [].
		</item>
		<item id="5">
			NO modifiques context.xml. Solo escribe los archivos de análisis por capítulo (.xml).
		</item>
		<item id="6">
			Retorna un array JSON con exactamente {{chapter_count}} objetos AuditOutput,
			uno por cada chapter id listado en &lt;chapters&gt;, en el mismo orden.
			El campo asvs_chapter de cada objeto debe coincidir con el id del capítulo correspondiente.
		</item>
		<item id="7">No coloques nada en la salida del chat; solo genera los archivos de salida requeridos.</item>
	</strict_instructions>

	<outputs>
{{outputs_xml}}
	</outputs>

	<output_contract><![CDATA[{{audit_output_grouped.json}}]]></output_contract>

	<component_context><![CDATA[{{context_md}}]]></component_context>

	<tactical_static_context>{{filtered_static_context}}</tactical_static_context>

	<chapters>
{{chapters_xml}}
	</chapters>
</prompt>
