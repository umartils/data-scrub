# DataScrub — Streamlit

Tools pembersihan data CSV & Excel berbasis Streamlit.

## Fitur
- Upload CSV & Excel (.xlsx)
- Hapus baris duplikat (opsional: keep terbaru berdasarkan kolom waktu)
- Hapus baris kosong (null/NaN)
- Filter multi-kategori — tambahkan sebanyak yang dibutuhkan
- Preview data sebelum & sesudah
- Download hasil sebagai CSV atau Excel

## Cara Menjalankan Lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

Buka http://localhost:8501

## Deploy ke Streamlit Community Cloud (Gratis)

1. Push project ini ke GitHub (repository public atau private)
2. Buka https://share.streamlit.io
3. Login dengan akun GitHub
4. Klik **"New app"**
5. Pilih repository, branch, dan file (`app.py`)
6. Klik **Deploy** — selesai!

URL app akan tersedia dalam format:
`https://[nama-app].streamlit.app`
