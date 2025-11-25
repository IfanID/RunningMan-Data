import re
import logging
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup

# Konfigurasi logging dasar
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ambil-tabel', methods=['POST'])
def ambil_tabel():
    data = request.get_json()
    url = data.get('url')
    logging.info(f"Menerima permintaan untuk URL: {url}")

    if not url:
        logging.warning("Permintaan diterima tanpa URL.")
        return jsonify({'error': 'URL tidak ditemukan'}), 400

    try:
        headers_req = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        respons = requests.get(url, headers=headers_req)
        respons.raise_for_status()
        
        sup = BeautifulSoup(respons.text, 'html.parser')
        tabel = sup.find('table', {'class': 'wikitable'})
        
        if not tabel:
            logging.error(f"Tidak ada tabel 'wikitable' yang ditemukan di {url}")
            return jsonify({'error': 'Tidak ada tabel dengan kelas "wikitable" yang ditemukan.'}), 404

        # Remove all nested tables
        for nested_table in tabel.find_all('table'):
            nested_table.decompose()

        caption_tag = tabel.find('caption')
        caption_text = caption_tag.get_text(strip=True) if caption_tag else "Tidak ada caption"

        header_row = tabel.find('tr')
        if not header_row:
            logging.error(f"Tidak ada baris header <tr> yang ditemukan di tabel pada {url}")
            return jsonify({'error': 'Baris header tabel tidak ditemukan.'}), 404
            
        headers = header_row.find_all('th')
        episode_col_index, date_col_index, guest_col_index, landmark_col_index, title_col_index = -1, -1, -1, -1, -1
        
        i = 0
        for th in headers:
            text_no_space = th.get_text(strip=True).lower().replace(' ', '')
            if 'ep.' in text_no_space:
                episode_col_index = i
            elif 'broadcastdate' in text_no_space or 'airdate' in text_no_space:
                date_col_index = i
            elif 'guest(s)' in text_no_space:
                guest_col_index = i
            elif 'landmark' in text_no_space:
                landmark_col_index = i
            elif 'title' in text_no_space:
                title_col_index = i
            
            i += int(th.get('colspan', 1))

        episodes_data = []
        rowspan_cells = {}

        for row in tabel.find('tbody').find_all('tr')[1:]:
            raw_cells = row.find_all(['th', 'td'], recursive=False)
            processed_cells = []
            col_offset = 0
            
            max_cols = 0
            for th in headers:
                max_cols += int(th.get('colspan', 1))
            
            i = 0
            while len(processed_cells) < max_cols:
                if i in rowspan_cells:
                    processed_cells.append(rowspan_cells[i]['cell'])
                    rowspan_cells[i]['rows_left'] -= 1
                    if rowspan_cells[i]['rows_left'] == 0:
                        del rowspan_cells[i]
                    i += 1
                else:
                    if col_offset < len(raw_cells):
                        cell = raw_cells[col_offset]
                        processed_cells.append(cell)
                        
                        colspan = int(cell.get('colspan', 1))
                        if cell.has_attr('rowspan'):
                            try:
                                if int(cell['rowspan']) > 1:
                                    for j in range(colspan):
                                        rowspan_cells[i + j] = {'rows_left': int(cell['rowspan']) - 1, 'cell': cell}
                            except ValueError: pass
                        i += colspan
                        col_offset += 1
                    else:
                        # Pad with empty cells if raw_cells is exhausted
                        processed_cells.append(BeautifulSoup('<td></td>', 'html.parser').td)
                        i += 1
            
            try:
                if not processed_cells or len(processed_cells) < max(episode_col_index, date_col_index, guest_col_index):
                    continue

                episode_number_raw = processed_cells[episode_col_index].get_text(strip=True)
                match = re.search(r'^\d+', episode_number_raw)
                
                if match:
                    episode_number = match.group(0)
                    
                    broadcast_date = ""
                    if date_col_index != -1 and len(processed_cells) > date_col_index and processed_cells[date_col_index]:
                        date_cell = processed_cells[date_col_index]
                        date_text = date_cell.find(string=True, recursive=False)
                        broadcast_date = date_text.strip() if date_text else ""

                    guests = "Tidak ada bintang tamu"
                    if guest_col_index != -1 and len(processed_cells) > guest_col_index and processed_cells[guest_col_index]:
                        guest_cell = processed_cells[guest_col_index]
                        guest_links = guest_cell.find_all('a')
                        guest_names = []
                        if guest_links:
                            for a in guest_links:
                                href = a.get('href', '')
                                text = a.get_text(strip=True)
                                if text.startswith('[') and text.endswith(']'): continue
                                if '_(band)' in href or '_(group)' in href: continue
                                guest_names.append(text)
                            guests = ', '.join(guest_names)
                        else:
                            guests = guest_cell.get_text(strip=True)
                        if not guests:
                            guests = "Tidak ada bintang tamu"

                    landmark = ""
                    if landmark_col_index != -1 and len(processed_cells) > landmark_col_index and processed_cells[landmark_col_index]:
                        landmark_cell = processed_cells[landmark_col_index]
                        landmark_raw = landmark_cell.get_text(separator=" ", strip=True)
                        landmark = re.sub(r'\s*\[\d+\]\s*', '', landmark_raw).strip()

                    title = ""
                    if title_col_index != -1 and len(processed_cells) > title_col_index and processed_cells[title_col_index]:
                        title_cell = processed_cells[title_col_index]
                        i_tag = title_cell.find('i')
                        if i_tag:
                            title = i_tag.get_text(strip=True)
                        else:
                            title = title_cell.get_text(strip=True)

                    episodes_data.append({
                        'episode': episode_number,
                        'date': broadcast_date,
                        'guests': guests,
                        'landmark': landmark,
                        'title': title
                    })
            except (IndexError, AttributeError) as e:
                logging.error(f"Error processing row: {e}")
                logging.error(f"Row data: {[cell.get_text(strip=True) if cell else '' for cell in processed_cells]}")
                continue

        logging.info(f"Berhasil mengekstrak {len(episodes_data)} episode dari {url}")
        return jsonify({
            'caption': caption_text,
            'episodes_data': episodes_data
        })

    except Exception as e:
        logging.exception(f"Terjadi error tak terduga saat memproses {url}:")
        return jsonify({'error': 'Terjadi kesalahan internal pada server. Periksa log untuk detail.'}), 500
@app.route('/ambil-summary')
def ambil_summary():
    try:
        with open('Running Man.html', 'r', encoding='utf-8') as f:
            content = f.read()
        
        sup = BeautifulSoup(content, 'html.parser')
        tabel = sup.find('table', {'class': 'infobox'})
        
        if not tabel:
            return jsonify({'error': 'Tidak ada tabel infobox yang ditemukan.'}), 404

        tbody = tabel.find('tbody')
        if not tbody:
            return jsonify({'error': 'Tidak ada tbody yang ditemukan.'}), 404

        for a in tbody.find_all('a', href=True):
            if a['href'].startswith('/'):
                a['href'] = 'https://en.wikipedia.org' + a['href']

        return jsonify({'summary_html': str(tbody)})

    except Exception as e:
        logging.exception("Terjadi error tak terduga saat memproses summary:")
        return jsonify({'error': 'Terjadi kesalahan internal pada server.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
