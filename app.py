import streamlit as st
import cv2
import numpy as np
import pytesseract
import pandas as pd
import re
import io
from PIL import Image
import os
import time

# ==========================================
# CONFIGURACIÓN DE TESSERACT
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# ==========================================

st.set_page_config(
    page_title="Escáner de Cheques Argentina", 
    layout="wide",
    page_icon="🏦"
)

st.title("🏦 Escáner de Cheques - Argentina")
st.markdown("Sube una foto del cheque o PDF para extraer datos automáticamente.")

# ==========================================
# SESSION_STATE
# ==========================================
if 'datos_extraidos' not in st.session_state:
    st.session_state.datos_extraidos = {
        'fecha': '',
        'monto': '',
        'nro_cheque': '',
        'documento': '',
        'banco_titular': ''
    }
if 'texto_ocr' not in st.session_state:
    st.session_state.texto_ocr = ''
if 'ingreso_manual' not in st.session_state:
    st.session_state.ingreso_manual = False

# ==========================================
# FUNCIONES
# ==========================================
def mejorar_imagen(img_array, nivel_mejora='normal'):
    """Mejora la calidad de la imagen para OCR"""
    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    if nivel_mejora == 'agresivo':
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                      cv2.THRESH_BINARY, 11, 2)
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        gray = cv2.filter2D(gray, -1, kernel)
    else:
        _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    
    return gray

def extraer_datos_cheque_argentino(texto):
    """Extrae datos específicos de cheques argentinos"""
    datos = {
        'fecha': '',
        'monto': '',
        'nro_cheque': '',
        'cuit': '',
        'dni': ''
    }
    
    # Limpiar texto
    texto_limpio = re.sub(r'[^\w\s\-.,$/:]', ' ', texto)
    
    # 1. FECHA - "04 de Marzo de 2026"
    meses = r'(Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic)'
    fecha_match = re.search(r'(?:EL|FECHA)?\s*(\d{1,2})\s+DE\s+' + meses + r'\s+DE\s+(\d{4})', texto_limpio, re.IGNORECASE)
    if fecha_match:
        dia = fecha_match.group(1)
        mes_nombre = fecha_match.group(2)
        anio = fecha_match.group(3)
        
        meses_dict = {
            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
            'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
            'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'ago': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12'
        }
        mes_num = meses_dict.get(mes_nombre.lower(), '01')
        datos['fecha'] = f"{dia}/{mes_num}/{anio}"
    else:
        fecha_match2 = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', texto_limpio)
        if fecha_match2:
            datos['fecha'] = f"{fecha_match2.group(1)}/{fecha_match2.group(2)}/{fecha_match2.group(3)}"
    
    # 2. MONTO
    monto_match = re.search(r'\$\s*(\d{1,3}(?:[.\d]*,\d{2}|\d*))', texto_limpio)
    if monto_match:
        datos['monto'] = monto_match.group(1).replace('.', '').replace(',', '.')
    else:
        montos = re.findall(r'\b(\d{5,8})\b', texto_limpio)
        if montos:
            datos['monto'] = montos[0]
    
    # 3. NÚMERO DE CHEQUE
    nro_match = re.search(r'(?:numero\s+de\s+cheque|n[°o]\s*cheque|cheque\s*n[°o])\s*:?\s*(\d{6,8})', texto_limpio, re.IGNORECASE)
    if nro_match:
        datos['nro_cheque'] = nro_match.group(1)
    else:
        from collections import Counter
        numeros = re.findall(r'\b(\d{6,8})\b', texto_limpio)
        if numeros:
            contador = Counter(numeros)
            datos['nro_cheque'] = contador.most_common(1)[0][0]
    
    # 4. CUIT/CUIL
    cuit_match = re.search(r'(?:CTA|CUIT|CUIL)\s*:?\s*(\d{2})[-\s](\d{8})[-\s](\d{1})', texto_limpio, re.IGNORECASE)
    if cuit_match:
        datos['cuit'] = f"{cuit_match.group(1)}-{cuit_match.group(2)}-{cuit_match.group(3)}"
    else:
        cuit_match2 = re.search(r'\b(20|23|24|25|27|30|33|34)(\d{9})\b', texto_limpio)
        if cuit_match2:
            cuit_raw = cuit_match2.group(1) + cuit_match2.group(2)
            datos['cuit'] = f"{cuit_raw[:2]}-{cuit_raw[2:10]}-{cuit_raw[10:]}"
        else:
            cuit_match3 = re.search(r'\b(\d{2})-(\d{8})-(\d{1})\b', texto_limpio)
            if cuit_match3:
                datos['cuit'] = f"{cuit_match3.group(1)}-{cuit_match3.group(2)}-{cuit_match3.group(3)}"
    
    # 5. DNI
    dni_match = re.search(r'(?:DNI|DOC\.?)\s*:?\s*(\d{6,8})', texto_limpio, re.IGNORECASE)
    if dni_match:
        datos['dni'] = dni_match.group(1)
    
    return datos

def formatear_fecha(texto):
    """Autocompleta / en la fecha"""
    # Remover todo lo que no sea número
    numeros = re.sub(r'[^0-9]', '', texto)
    
    # Limitar a 8 dígitos (DDMMYYYY)
    numeros = numeros[:8]
    
    # Formatear
    if len(numeros) <= 2:
        return numeros
    elif len(numeros) <= 4:
        return f"{numeros[:2]}/{numeros[2:]}"
    else:
        return f"{numeros[:2]}/{numeros[2:4]}/{numeros[4:]}"

# ==========================================
# SIDEBAR
# ==========================================
with st.sidebar:
    st.header("⚙️ Configuración")
    nivel_mejora = st.selectbox(
        "Nivel de mejora de imagen:",
        ['normal', 'agresivo'],
        help='Usá "agresivo" si la imagen es muy mala'
    )
    
    st.markdown("---")
    st.info("💡 **Consejos:**\n- Buena iluminación\n- Foto nítida\n- Todo el cheque visible")
    
    st.markdown("---")
    st.caption("v1.0 - Escáner de Cheques Argentina")

# ==========================================
# UPLOAD
# ==========================================
uploaded_file = st.file_uploader(
    "📸 Sube la foto o PDF del cheque", 
    type=["jpg", "jpeg", "png", "pdf"],
    help="Formatos soportados: JPG, PNG, PDF"
)

if uploaded_file is not None:
    try:
        # Convertir PDF a imagen
        if uploaded_file.type == "application/pdf":
            st.info("📄 Procesando PDF...")
            try:
                from pdf2image import convert_from_bytes
                pdf_images = convert_from_bytes(uploaded_file.read())
                image = pdf_images[0]
                st.success("✅ PDF convertido")
            except Exception as e:
                st.error(f"❌ Error con PDF: {str(e)}")
                st.warning("💡 Asegurate de tener Poppler instalado")
                st.stop()
        else:
            image = Image.open(uploaded_file)
        
        img_array = np.array(image)
        img_procesada = mejorar_imagen(img_array, nivel_mejora)
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.image(image, caption="Imagen Original", use_column_width=True)
        
        with col2:
            st.image(img_procesada, caption="Imagen Procesada", use_column_width=True, 
                    output_format='PNG')

        # Botón de extracción
        if st.button("🔍 Extraer Datos del Cheque", type="primary", use_container_width=True):
            with st.spinner("Analizando cheque..."):
                custom_config = r'--oem 3 --psm 6'
                texto_extraido = pytesseract.image_to_string(img_procesada, lang='spa', config=custom_config)
                
                st.session_state.texto_ocr = texto_extraido
                
                datos = extraer_datos_cheque_argentino(texto_extraido)
                
                st.session_state.datos_extraidos['fecha'] = datos['fecha']
                st.session_state.datos_extraidos['monto'] = datos['monto']
                st.session_state.datos_extraidos['nro_cheque'] = datos['nro_cheque']
                st.session_state.datos_extraidos['documento'] = datos['cuit'] if datos['cuit'] else datos['dni']
                
                st.success("✅ Datos extraídos. Revisá y corregí si es necesario.")
                st.rerun()

        # Formulario de edición
        if st.session_state.texto_ocr or uploaded_file:
            st.markdown("---")
            st.subheader("✏️ Datos del Cheque")
            
            st.session_state.ingreso_manual = st.checkbox(
                "📝 Ingresar CUIT/DNI manualmente", 
                value=st.session_state.ingreso_manual
            )
            
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                fecha_input = st.text_input(
                    "Fecha (DD/MM/AAAA)", 
                    value=st.session_state.datos_extraidos['fecha'],
                    help="Formato: DD/MM/AAAA"
                )
                # Auto-formatear fecha
                if fecha_input:
                    fecha_formateada = formatear_fecha(fecha_input)
                    fecha_final = fecha_formateada
                else:
                    fecha_final = ""
            
            with c2:
                monto_final = st.text_input(
                    "Monto", 
                    value=st.session_state.datos_extraidos['monto']
                )
            
            with c3:
                nro_cheque_final = st.text_input(
                    "N° Cheque", 
                    value=st.session_state.datos_extraidos['nro_cheque']
                )
            
            with c4:
                if st.session_state.ingreso_manual:
                    documento_final = st.text_input(
                        "CUIT/DNI (Manual)", 
                        value="",
                        help="Ingresá el CUIT con o sin guiones"
                    )
                else:
                    documento_final = st.text_input(
                        "CUIT/DNI detectado", 
                        value=st.session_state.datos_extraidos['documento']
                    )
                    if not documento_final:
                        st.warning("⚠️ No se detectó")
            
            banco_titular = st.text_input(
                "Banco / Titular", 
                value=st.session_state.datos_extraidos['banco_titular']
            )
            
            # Actualizar session state
            st.session_state.datos_extraidos['fecha'] = fecha_final
            st.session_state.datos_extraidos['monto'] = monto_final
            st.session_state.datos_extraidos['nro_cheque'] = nro_cheque_final
            st.session_state.datos_extraidos['documento'] = documento_final
            st.session_state.datos_extraidos['banco_titular'] = banco_titular

            # ==========================================
            # VERIFICACIÓN BCRA CON BOTÓN COPIAR
            # ==========================================
            st.markdown("---")
            st.subheader("🛡️ Verificación - BCRA")
            
            if documento_final:
                # Limpiar documento
                doc_limpio = documento_final.replace("-", "").replace(" ", "")
                
                if len(doc_limpio) == 11:
                    cuit_formateado = f"{doc_limpio[:2]}-{doc_limpio[2:10]}-{doc_limpio[10:]}"
                else:
                    cuit_formateado = doc_limpio
                
                # URL del BCRA
                url_bcra = "https://www.bcra.gob.ar/situacion-crediticia/"
                
                # Mostrar CUIT con botón de copiar
                st.success("📋 **CUIT/DNI para consultar:**")
                
                col_cuit1, col_cuit2 = st.columns([3, 1])
                
                with col_cuit1:
                    st.markdown(f"""
                    <div style='background-color: #0066cc; color: white; padding: 15px; 
                                border-radius: 8px; text-align: center; font-size: 20px; 
                                font-weight: bold; margin: 10px 0;'>
                        {cuit_formateado}
                    </div>
                    """, unsafe_allow_html=True)
                
                with col_cuit2:
                    # Botón de copiar usando st.code (la mejor forma en Streamlit)
                    st.code(cuit_formateado.replace("-", ""), language=None)
                    st.caption("Copiá haciendo clic")
                
                # Botón al BCRA
                st.link_button(
                    "🔎 IR AL BCRA - Situación Crediticia", 
                    url_bcra, 
                    type="secondary",
                    use_container_width=True
                )
                
                st.info(f"""
                **📌 Instrucciones:**
                1. Copiá el número de arriba (clic en el recuadro)
                2. Hacé clic en el botón azul para ir al BCRA
                3. Pegá el CUIT: **{cuit_formateado}**
                4. Completá el captcha y consultá
                """)
            else:
                st.warning("⚠️ Ingresá el CUIT/DNI arriba")

            # ==========================================
            # GENERAR EXCEL
            # ==========================================
            st.markdown("---")
            if st.button("💾 Guardar en Excel", type="primary", use_container_width=True):
                df = pd.DataFrame([{
                    "Fecha": fecha_final,
                    "N° Cheque": nro_cheque_final,
                    "Monto": monto_final,
                    "CUIT/DNI Emisor": documento_final,
                    "Banco/Titular": banco_titular
                }])
                
                excel_buffer = io.BytesIO()
                df.to_excel(excel_buffer, index=False, engine='openpyxl')
                
                st.success("¡Excel generado!")
                st.download_button(
                    label="⬇️ Descargar Excel",
                    data=excel_buffer,
                    file_name=f"cheque_{nro_cheque_final or 'sin_numero'}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            # Modo debug
            with st.expander("🛠️ Ver texto del OCR"):
                st.text_area("Texto detectado:", st.session_state.texto_ocr, height=200)
                st.write("**Datos extraídos:**")
                st.write(f"- Fecha: {st.session_state.datos_extraidos['fecha']}")
                st.write(f"- Monto: {st.session_state.datos_extraidos['monto']}")
                st.write(f"- N° Cheque: {st.session_state.datos_extraidos['nro_cheque']}")
                st.write(f"- Documento: {st.session_state.datos_extraidos['documento']}")

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        st.exception(e)
else:
    st.info("👆 Subí un archivo para comenzar")
    st.markdown("""
    **Características:**
    - ✅ Extracción automática de datos
    - ✅ Soporte para PDF e imágenes
    - ✅ Verificación en BCRA
    - ✅ Exportación a Excel
    - ✅ 100% gratuito
    """)