import streamlit as st
import pandas as pd
import io
import json
import re
from datetime import datetime

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Data Cleaning Tools",
    page_icon="./mn-icon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Font & base */
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&family=Syne:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0D0D0D;
    }
    section[data-testid="stSidebar"] * {
        color: #F5F2EB !important;
    }
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stCheckbox label,
    section[data-testid="stSidebar"] .stNumberInput label {
        color: #8A8480 !important;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #F5F2EB !important;
        font-family: 'Syne', sans-serif;
    }
    section[data-testid="stSidebar"] hr {
        border-color: #2a2a2a;
    }

    /* Main area */
    .main .block-container { padding-top: 2rem; max-width: 1200px; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #EDE9DF;
        border: 1px solid #D9D4C8;
        border-radius: 12px;
        padding: 1rem;
    }

    /* Headings */
    h1 { font-family: 'Syne', sans-serif !important; font-size: 2rem !important; }
    h2, h3 { font-family: 'Syne', sans-serif !important; }

    /* Log box */
    .log-box {
        background: #0D0D0D;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
        color: #aaa;
        line-height: 1.8;
    }
    .log-box .log-item::before { content: "› "; color: #D4622A; }

    /* Filter section card */
    .filter-card {
        background: #EDE9DF;
        border: 1px solid #D9D4C8;
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 0.75rem;
    }

    /* Badge */
    .badge {
        display: inline-block;
        background: rgba(212,98,42,0.12);
        color: #D4622A;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 20px;
        font-family: 'JetBrains Mono', monospace;
    }

    /* Hide streamlit branding */
    #MainMenu, footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

DATETIME_HINTS = [
    "time", "timestamp", "date", "datetime", "waktu", "tanggal",
    "created", "updated", "modified", "at", "recorded", "logged",
]


@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    else:
        return pd.read_excel(io.BytesIO(file_bytes))


def detect_datetime_columns(df: pd.DataFrame) -> list[dict]:
    result = []
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            parsed = series
        else:
            if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
                continue
            try:
                parsed = pd.to_datetime(series, infer_datetime_format=True, errors="raise")
            except Exception:
                continue

        has_time = parsed.dropna().apply(lambda x: x.hour != 0 or x.minute != 0 or x.second != 0).any()
        has_second = parsed.dropna().apply(lambda x: x.second != 0).any()
        resolution = "second" if has_second else ("minute" if has_time else "date")
        sample = str(parsed.dropna().iloc[0]) if not parsed.dropna().empty else ""

        hint_score = any(h in col.lower() for h in DATETIME_HINTS)
        result.append({"name": col, "sample": sample, "resolution": resolution, "hint": hint_score})

    result.sort(key=lambda x: x["hint"], reverse=True)
    return result


def get_categorical_columns(df: pd.DataFrame, max_unique: int = 50) -> list[str]:
    """Kolom yang cocok dijadikan filter kategori (unique values <= max_unique)."""
    return [col for col in df.columns if 1 < df[col].nunique() <= max_unique]


def apply_cleaning(
    df: pd.DataFrame,
    remove_duplicates: bool,
    dedup_time_col: str | None,
    dedup_subset: list[str],
    exclude_paid_groups: bool,
    remove_nulls: bool,
    filters: list[dict],  # [{column, values}]
) -> tuple[pd.DataFrame, list[str]]:
    log = []
    original = len(df)

    # 1. Hapus duplikat
    if remove_duplicates:
        before = len(df)

        # Tentukan kolom kunci subset
        if dedup_time_col and dedup_time_col in df.columns:
            df[dedup_time_col] = pd.to_datetime(
                df[dedup_time_col], infer_datetime_format=True, errors="coerce"
            )
            subset = (
                [c for c in dedup_subset if c in df.columns and c != dedup_time_col]
                or [c for c in df.columns if c != dedup_time_col]
            )
        else:
            subset = [c for c in dedup_subset if c in df.columns] or list(df.columns)

        # Tandai baris yang merupakan bagian dari grup duplikat
        is_dup_group = df.duplicated(subset=subset, keep=False)

        # ── Cek kolom State: buang seluruh grup yang ada nilai "Paid" ──────
        paid_group_rows_removed = 0
        if exclude_paid_groups and "State" in df.columns:
            # Buat group key per baris
            df["_group_key"] = df[subset].astype(str).agg("|".join, axis=1)

            # Temukan group key yang di dalamnya ada baris dengan State == "Paid"
            dup_df = df[is_dup_group].copy()
            paid_group_keys = set(
                dup_df.loc[dup_df["State"].astype(str) == "Paid", "_group_key"].unique()
            )

            if paid_group_keys:
                # Hapus SEMUA baris yang group key-nya ada di paid_group_keys
                mask_paid_group = df["_group_key"].isin(paid_group_keys)
                paid_group_rows_removed = mask_paid_group.sum()
                df = df[~mask_paid_group].copy()
                # Recalculate is_dup_group setelah penghapusan grup Paid
                is_dup_group = df.duplicated(subset=subset, keep=False)
                log.append(
                    f"Hapus grup duplikat ber-State 'Paid': {paid_group_rows_removed} baris dihapus "
                    f"({len(paid_group_keys)} grup)"
                )
            else:
                log.append("Cek State 'Paid': tidak ada grup duplikat dengan State 'Paid' ditemukan")

            df = df.drop(columns=["_group_key"])

        # ── Dedup sisa: simpan terbaru atau keep first ────────────────────
        if dedup_time_col and dedup_time_col in df.columns:
            df = df.sort_values(dedup_time_col, ascending=False)
            df = df.drop_duplicates(subset=subset, keep="first")
            df = df.sort_values(dedup_time_col, ascending=True).reset_index(drop=True)
            removed_dedup = before - paid_group_rows_removed - len(df)
            log.append(
                f"Hapus duplikat (keep terbaru via '{dedup_time_col}'): {removed_dedup} baris dihapus"
            )
        else:
            df = df.drop_duplicates(subset=subset, keep="first")
            removed_dedup = before - paid_group_rows_removed - len(df)
            log.append(f"Hapus duplikat: {removed_dedup} baris dihapus")

    # 2. Hapus baris kosong
    if remove_nulls:
        before = len(df)
        df = df.dropna()
        log.append(f"Hapus baris kosong: {before - len(df)} baris dihapus")

    # 3. Filter per kategori (bisa lebih dari 1)
    for f in filters:
        col, vals = f["column"], f["values"]
        if col in df.columns and vals:
            before = len(df)
            df = df[df[col].astype(str).isin([str(v) for v in vals])]
            log.append(f"Filter '{col}' ({len(vals)} nilai dipilih): tersisa {len(df)} baris, {before - len(df)} dihapus")

    total_removed = original - len(df)
    log.append(f"── Total: {original} → {len(df)} baris ({total_removed} dihapus, {round(total_removed/original*100) if original else 0}%)")
    return df, log


def to_download_bytes(df: pd.DataFrame, fmt: str) -> tuple[bytes, str, str]:
    buf = io.BytesIO()
    filename = uploaded.name.rsplit(".", 1)[0]
    if fmt == "xlsx":
        df.to_excel(buf, index=False, engine="openpyxl")
        return buf.getvalue(), f"{filename}_cleaned_data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        df.to_csv(buf, index=False)
        return buf.getvalue(), f"{filename}_cleaned_data.csv", "text/csv"


# ── Session state init ──────────────────────────────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = None
if "filters" not in st.session_state:
    st.session_state.filters = []  # list of {column, values}
if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "log" not in st.session_state:
    st.session_state.log = []


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## Data Cleaning Tools")
    st.divider()

    # ── Upload ────────────────────────────────────────────────────────────
    st.markdown("### Upload File")
    uploaded = st.file_uploader(
        "Pilih file CSV atau Excel",
        type=["csv", "xlsx", "xls"],
        label_visibility="collapsed",
    )

    if uploaded:
        with st.spinner("Membaca file..."):
            df_raw = load_file(uploaded.read(), uploaded.name)
            st.session_state.df = df_raw
            # Reset hasil jika file baru
            st.session_state.result_df = None
            st.session_state.log = []

    if st.session_state.df is None:
        st.info("Upload file untuk mulai")
        st.stop()

    df = st.session_state.df
    cat_cols = get_categorical_columns(df)
    dt_cols = detect_datetime_columns(df)

    st.divider()

    # ── Hapus Duplikat ────────────────────────────────────────────────────
    st.markdown("### Hapus Duplikat")
    remove_dups = st.checkbox("Aktifkan", value=True, key="remove_dups")

    dedup_time_col = None
    dedup_subset = []
    exclude_paid_groups = False
    if remove_dups:
        # Opsi State = Paid
        has_state_col = "State" in df.columns
        if has_state_col:
            exclude_paid_groups = st.checkbox(
                "Buang seluruh grup duplikat yang mengandung State = 'Paid'",
                value=True,
                key="exclude_paid",
                help="Jika dalam satu grup duplikat ada baris dengan State='Paid', semua baris dalam grup tersebut akan dihapus seluruhnya.",
            )
        else:
            st.caption("⚠️ Kolom 'State' tidak ditemukan di file ini")

        dt_names = ["— Tidak pakai (hapus biasa) —"] + [
            f"{c['name']} · {c['resolution']}" for c in dt_cols
        ]
        dt_choice = st.selectbox("Kolom waktu (keep terbaru)", dt_names, key="dt_col")
        if dt_choice != dt_names[0]:
            dedup_time_col = dt_cols[dt_names.index(dt_choice) - 1]["name"]
            sample = dt_cols[dt_names.index(dt_choice) - 1]["sample"]
            st.caption(f"Contoh: `{sample}`")

            non_time_cols = [c for c in df.columns if c != dedup_time_col]
            dedup_subset = st.multiselect(
                "Kolom kunci duplikat (kosong = semua)",
                non_time_cols,
                key="dedup_subset",
            )

    st.divider()

    # ── Hapus Baris Kosong ────────────────────────────────────────────────
    st.markdown("### Hapus Baris Kosong")
    remove_nulls = st.checkbox("Aktifkan", value=True, key="remove_nulls")

    st.divider()

    # ── Filter Kategori ───────────────────────────────────────────────────
    st.markdown("### Filter Kategori")

    # Jumlah filter yang ingin ditambahkan
    n_filters = st.number_input(
        "Jumlah filter kolom",
        min_value=0,
        max_value=len(cat_cols) if cat_cols else 0,
        value=min(1, len(cat_cols)),
        step=1,
        key="n_filters",
    )

    filters: list[dict] = []
    used_cols: list[str] = []

    for i in range(int(n_filters)):
        st.markdown(f"**Filter {i + 1}**")
        available_cols = [c for c in cat_cols if c not in used_cols]
        if not available_cols:
            st.caption("Tidak ada kolom kategori tersisa")
            break

        sel_col = st.selectbox(
            f"Kolom filter {i + 1}",
            available_cols,
            key=f"filter_col_{i}",
            label_visibility="collapsed",
        )
        used_cols.append(sel_col)

        unique_vals = df[sel_col].dropna().astype(str).unique().tolist()
        sel_vals = st.multiselect(
            f"Nilai yang disimpan (filter {i + 1})",
            unique_vals,
            default=unique_vals,
            key=f"filter_vals_{i}",
            label_visibility="collapsed",
        )
        filters.append({"column": sel_col, "values": sel_vals})

        if i < int(n_filters) - 1:
            st.markdown("---")

    st.divider()

    # ── Output format & tombol ────────────────────────────────────────────
    st.markdown("### Output")
    output_fmt = st.radio("Format", ["xlsx", "csv"], horizontal=True, key="output_fmt")

    run_btn = st.button("🚀 Bersihkan Data", use_container_width=True, type="primary")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════════════════════════════
df = st.session_state.df

st.markdown("# Data Cleaning Tools")
st.markdown("Bersihkan data CSV & Excel — hapus duplikat, filter kategori, dan unduh hasilnya.")
st.divider()

# ── Stats overview ───────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Baris", f"{len(df):,}")
col2.metric("Total Kolom", len(df.columns))
col3.metric("Baris Duplikat", f"{df.duplicated().sum():,}")
col4.metric("Baris Kosong", f"{df.isnull().any(axis=1).sum():,}")

st.divider()

# ── Tabs: Preview & Analisis ─────────────────────────────────────────────────
tab_preview, tab_info, tab_result = st.tabs(["Preview Data", "Info Kolom", "Hasil Cleaning"])

with tab_preview:
    st.markdown("**5 baris pertama data mentah**")
    st.dataframe(df.head(5), use_container_width=True, hide_index=True)

with tab_info:
    info_rows = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        null_count = df[col].isnull().sum()
        unique_count = df[col].nunique()
        sample = str(df[col].dropna().iloc[0]) if not df[col].dropna().empty else "—"
        info_rows.append({
            "Kolom": col,
            "Tipe Data": dtype,
            "Null": null_count,
            "Unik": unique_count,
            "Contoh Nilai": sample[:60],
        })
    st.dataframe(pd.DataFrame(info_rows), use_container_width=True, hide_index=True)

with tab_result:
    # ── Jalankan cleaning ────────────────────────────────────────────────
    if run_btn:
        with st.spinner("Memproses data..."):
            result_df, log = apply_cleaning(
                df.copy(),
                remove_duplicates=remove_dups,
                dedup_time_col=dedup_time_col,
                dedup_subset=dedup_subset,
                exclude_paid_groups=exclude_paid_groups,
                remove_nulls=remove_nulls,
                filters=filters,
            )
            st.session_state.result_df = result_df
            st.session_state.log = log

    if st.session_state.result_df is not None:
        result_df = st.session_state.result_df
        log = st.session_state.log
        original_rows = len(df)
        final_rows = len(result_df)
        removed = original_rows - final_rows

        # Stats
        r1, r2, r3 = st.columns(3)
        r1.metric("Sebelum", f"{original_rows:,} baris")
        r2.metric("Sesudah", f"{final_rows:,} baris", delta=f"-{removed:,}")
        r3.metric("Dihapus", f"{removed:,} baris ({round(removed/original_rows*100) if original_rows else 0}%)")

        st.markdown("**Log Proses**")
        log_html = "<div class='log-box'>" + "".join(
            f"<div class='log-item'>{line}</div>" for line in log
        ) + "</div>"
        st.markdown(log_html, unsafe_allow_html=True)

        st.markdown("**Preview Hasil (5 baris pertama)**")
        st.dataframe(result_df.head(5), use_container_width=True, hide_index=True)

        # Download
        file_bytes, filename, mime = to_download_bytes(result_df, output_fmt)
        st.download_button(
            label=f"⬇️ Unduh {filename}",
            data=file_bytes,
            file_name=filename,
            mime=mime,
            use_container_width=True,
            type="primary",
        )
    else:
        st.info("Klik **Bersihkan Data** di sidebar untuk memulai proses.")
