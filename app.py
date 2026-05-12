import sqlite3
import textwrap
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

# GitHub / アップロード先が「このフォルダの最新」と一致しているか確認用（日付を更新してコミット）
APP_BUILD_ID = "2026-05-13-footer-blank"

DB_PATH = Path("projects.db")
OUTPUT_DIR = Path("outputs")
BOARD_BG = (60, 63, 70)
WHITE = (255, 255, 255)


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_latest_project_name() -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT project_name FROM projects ORDER BY updated_at DESC, id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def upsert_project_name(project_name: str) -> None:
    if not project_name.strip():
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO projects (project_name, updated_at) VALUES (?, ?)",
        (project_name.strip(), now),
    )
    conn.commit()
    conn.close()


def load_japanese_font(size: int) -> ImageFont.FreeTypeFont:
    """日本語表示用フォント。macOS はヒラギノ、Linux（Streamlit Cloud 等）は Noto を使用。"""
    base = Path(__file__).resolve().parent
    try_paths: List[Tuple[str, Optional[int]]] = []

    bundled = base / "fonts" / "NotoSansJP-Regular.otf"
    if bundled.exists():
        try_paths.append((str(bundled), None))

    for p in (
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ):
        try_paths.append((p, None))

    for noto_dir in (
        Path("/usr/share/fonts/opentype/noto"),
        Path("/usr/share/fonts/truetype/noto"),
    ):
        if not noto_dir.is_dir():
            continue
        for pattern in (
            "NotoSansCJKjp*.otf",
            "NotoSansJP*.otf",
            "NotoSansJP*.ttf",
            "NotoSerifJP*.otf",
        ):
            for fp in sorted(noto_dir.glob(pattern)):
                try_paths.append((str(fp), None))

    cjk_ttc = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not cjk_ttc.exists():
        cjk_ttc = Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")
    if cjk_ttc.exists():
        for idx in (2, 3, 0, 1, 4, 5, 6, 7):
            try_paths.append((str(cjk_ttc), idx))

    for path_str, idx in try_paths:
        if not Path(path_str).exists():
            continue
        try:
            if idx is not None and path_str.lower().endswith(".ttc"):
                return ImageFont.truetype(path_str, size=size, index=idx)
            return ImageFont.truetype(path_str, size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def normalize_value(value: str) -> str:
    text = (value or "").strip()
    if text == "なし":
        return ""
    return text


FOOTER_VALUE_BASE_PX = 34  # 「〇〇」と同じ目安の本文サイズ（幅に応じてのみ縮小）


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    stroke_width: int = 1,
) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width, stroke_fill=WHITE)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_text_centered_in_rect(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    rect: Tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = rect
    tw, th = _text_size(draw, text, font)
    cx = left + max(0, (right - left - tw) // 2)
    cy = top + max(0, (bottom - top - th) // 2)
    draw.text((cx, cy), text, font=font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)


def draw_value_in_row_cell(
    draw: ImageDraw.ImageDraw,
    value: str,
    cell_left: int,
    cell_top: int,
    cell_w: int,
    cell_h: int,
    pad: int = 8,
) -> None:
    """値を行の高さ・幅に収まるよう単行（縮小）または最大2行で描画。"""
    inner_left = cell_left + pad
    inner_w = max(10, cell_w - 2 * pad)
    inner_top = cell_top + pad
    inner_h = max(10, cell_h - 2 * pad)
    raw = (value or "").strip() or " "
    for size in (30, 26, 22, 18):
        vf = load_japanese_font(size)
        tw, th = _text_size(draw, raw, vf)
        if tw <= inner_w and th <= inner_h:
            ty = cell_top + (cell_h - th) // 2
            draw.text(
                (inner_left, ty),
                raw,
                font=vf,
                fill=WHITE,
                stroke_width=1,
                stroke_fill=WHITE,
            )
            return
    vf = load_japanese_font(16)
    max_chars = max(4, inner_w // 16)
    lines = textwrap.wrap(raw, width=max_chars)[:2]
    if not lines:
        lines = [" "]
    joined = "\n".join(lines)
    tw, th = _text_size(draw, joined, vf)
    if th > inner_h:
        joined = lines[0][: max(0, max_chars - 1)] + "…"
    draw.multiline_text(
        (inner_left, inner_top),
        joined,
        font=vf,
        fill=WHITE,
        spacing=2,
        stroke_width=1,
        stroke_fill=WHITE,
    )


def draw_table_row(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    left: int,
    top: int,
    total_w: int,
    row_h: int,
    label_col_w: int,
    label_font: ImageFont.FreeTypeFont,
) -> None:
    """右側表の1行。ラベル列と値列を枠線で区切り、文字を行内に収める。"""
    val_col_x0 = left + label_col_w
    draw.line([(left, top + row_h), (left + total_w, top + row_h)], fill=WHITE, width=2)
    draw.line([(val_col_x0, top), (val_col_x0, top + row_h)], fill=WHITE, width=2)
    _, lh = _text_size(draw, label, label_font)
    ly = top + max(0, (row_h - lh) // 2)
    draw.text(
        (left + 8, ly),
        label,
        font=label_font,
        fill=WHITE,
        stroke_width=1,
        stroke_fill=WHITE,
    )
    draw_value_in_row_cell(draw, value, val_col_x0, top, total_w - label_col_w, row_h)


def draw_footer_value_like_maru(
    draw: ImageDraw.ImageDraw,
    value: str,
    rect: Tuple[int, int, int, int],
    base_px: int = FOOTER_VALUE_BASE_PX,
) -> None:
    """施工者・立会者の入力欄。未入力は何も描かず、入力時のみ〇〇相当サイズで中央表示。"""
    display = (value or "").strip()
    if not display:
        return
    left, top, right, bottom = rect
    w = right - left
    h = bottom - top
    pad = 10
    inner_w = max(12, w - 2 * pad)
    inner_h = max(12, h - 2 * pad)
    for size in range(base_px, 14, -2):
        vf = load_japanese_font(size)
        tw, th = _text_size(draw, display, vf)
        if tw <= inner_w and th <= inner_h:
            cx = left + max(pad, (w - tw) // 2)
            cy = top + max(pad, (h - th) // 2)
            draw.text((cx, cy), display, font=vf, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
            return
    vf = load_japanese_font(14)
    max_chars = max(2, inner_w // 14)
    short = (display[: max_chars - 1] + "…") if len(display) > max_chars - 1 else display
    tw, th = _text_size(draw, short, vf)
    cx = left + max(pad, (w - tw) // 2)
    cy = top + max(pad, (h - th) // 2)
    draw.text((cx, cy), short, font=vf, fill=WHITE, stroke_width=1, stroke_fill=WHITE)


def draw_footer_four_columns(
    draw: ImageDraw.ImageDraw,
    foot_top: int,
    width: int,
    height: int,
    contractor: str,
    observer: str,
) -> None:
    """施工者 | 入力 | 立会者 | 入力（1行4列。ラベル列はやや狭く、値は〇〇相当サイズ）。"""
    label_font = load_japanese_font(38)
    # ラベル列 220px、値列 330px（計 1100）
    x1, x2, x3 = 220, 550, 770
    for vx in (x1, x2, x3):
        draw.line([(vx, foot_top), (vx, height)], fill=WHITE, width=3)
    c1 = (0, foot_top, x1, height)
    c2 = (x1, foot_top, x2, height)
    c3 = (x2, foot_top, x3, height)
    c4 = (x3, foot_top, width, height)
    draw_text_centered_in_rect(draw, "施工者", label_font, c1)
    draw_text_centered_in_rect(draw, "立会者", label_font, c3)
    draw_footer_value_like_maru(draw, contractor, c2)
    draw_footer_value_like_maru(draw, observer, c4)


def generate_blackboard(
    data: Dict[str, str],
    reference_image: Optional[Image.Image] = None,
    size: Tuple[int, int] = (1100, 760),
) -> Image.Image:
    width, height = size
    img = Image.new("RGB", size, BOARD_BG)
    draw = ImageDraw.Draw(img)
    title_font = load_japanese_font(42)
    label_font = load_japanese_font(20)
    small_font = load_japanese_font(20)

    foot_h = 94
    foot_top = height - foot_h

    draw.rectangle([(4, 4), (width - 4, height - 4)], outline=WHITE, width=4)

    top_h = 180
    draw.line([(0, 90), (width, 90)], fill=WHITE, width=3)
    draw.line([(250, 0), (250, top_h)], fill=WHITE, width=3)
    draw.text((20, 16), "工事名", font=title_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    draw.text((20, 104), "工事場所", font=title_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    draw.text((270, 20), data.get("project_name", ""), font=title_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    draw.text((270, 114), data.get("location", ""), font=title_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)

    draw.line([(500, top_h), (500, foot_top)], fill=WHITE, width=3)
    draw.line([(0, foot_top), (width, foot_top)], fill=WHITE, width=3)

    ref_left, ref_top = 28, top_h + 20
    ref_right, ref_bottom = 500, foot_top - 12
    draw.rectangle([(ref_left, ref_top), (ref_right, ref_bottom)], outline=WHITE, width=2)
    if reference_image is not None:
        ref_w = ref_right - ref_left - 8
        ref_h = ref_bottom - ref_top - 8
        ref_img = reference_image.convert("RGB")
        ref_img.thumbnail((ref_w, ref_h), Image.Resampling.LANCZOS)
        paste_x = ref_left + (ref_w - ref_img.width) // 2 + 4
        paste_y = ref_top + (ref_h - ref_img.height) // 2 + 4
        img.paste(ref_img, (paste_x, paste_y))
    else:
        draw.text((200, top_h + 210), "参考図", font=title_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
        draw.text((122, top_h + 280), "※ 今回は画像を配置しない構成", font=small_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    x = 520
    w = width - x - 24

    # Shift the right-side table block upward to reduce top blank space.
    right_block_top = top_h - 70

    # Right top dedicated area for shot date
    date_top = right_block_top
    date_bottom = right_block_top + 48
    draw.rectangle([(x + 110, date_top), (width - 12, date_bottom)], outline=WHITE, width=2)
    shot = data.get("shot_date", "")
    sw, sh = _text_size(draw, shot, small_font)
    sx = x + 110 + max(8, ((width - 12) - (x + 110) - sw) // 2)
    sy = date_top + max(4, (date_bottom - date_top - sh) // 2)
    draw.text((sx, sy), shot, font=small_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)

    y = right_block_top + 58
    row_h = 52
    label_col_w = 172
    draw_table_row(draw, "撮影階", data.get("floor", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "X通り", data.get("x_line", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "Y通り", data.get("y_line", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "撮影箇所", data.get("location", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "工種", data.get("work_type", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "種別", data.get("category", ""), x, y, w, row_h, label_col_w, label_font)
    y += row_h
    draw_table_row(draw, "細別", data.get("subcategory", ""), x, y, w, row_h, label_col_w, label_font)
    draw.text((x, y + 52), "施工管理値", font=label_font, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    # Keep this area intentionally blank (no frame/text) for free space below the label.

    draw_footer_four_columns(
        draw,
        foot_top,
        width,
        height,
        data.get("contractor", ""),
        data.get("observer", ""),
    )
    return img


def compose_blackboard(
    photo: Image.Image,
    blackboard: Image.Image,
    position: str,
    margin: int = 24,
    ratio: float = 0.42,
) -> Image.Image:
    base = photo.convert("RGB")
    board_w = int(base.width * ratio)
    board_h = int(blackboard.height * board_w / blackboard.width)
    board_resized = blackboard.resize((board_w, board_h), Image.Resampling.LANCZOS)
    board_resized = ImageEnhance.Sharpness(board_resized).enhance(1.2)

    if position == "左下":
        x = margin
    else:
        x = base.width - board_w - margin
    y = base.height - board_h - margin

    result = base.copy()
    result.paste(board_resized, (x, y))
    return result


def to_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def save_output(img: Image.Image) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"composed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    img.save(path)
    return path


def main() -> None:
    st.set_page_config(page_title="電子小黒板 合成", page_icon="🧾", layout="wide")
    init_db()
    latest_project_name = get_latest_project_name()

    st.title("🧾 写真アップロード時の小黒板データ入力")
    st.caption("右側フォーム入力を反映した小黒板を生成し、工事写真へ合成します。")
    st.caption(
        f"ビルド: {APP_BUILD_ID}（フッター値欄: 未入力は空白・入力時のみ表示）"
    )
    st.info(
        f"**反映確認:** この行のビルドが **{APP_BUILD_ID}** になっていない場合、"
        "Streamlit Cloud が **別ブランチ／別リポジトリ／古いコミット**を見ています。"
        " GitHub に `app.py`・`packages.txt`・`fonts/NotoSansJP-Regular.otf` を push したうえで、"
        "Cloud の **Manage app → Reboot**（または再デプロイ）を実行してください。"
    )

    upload = st.file_uploader("工事写真をアップロード", type=["jpg", "jpeg", "png"])
    col_preview, col_form = st.columns([1, 1])

    with col_form:
        st.subheader("入力フォーム")
        with st.form("blackboard_form"):
            project_name = st.text_input("工事名", value=latest_project_name, placeholder="例: ○○邸 改修工事")
            floor = st.text_input("撮影階", value="")
            location = st.text_input("撮影箇所", value="")
            work_type = st.text_input("工種", value="")
            category = st.text_input("種別", value="")
            subcategory = st.text_input("細別", value="")
            control_value = st.text_area("施工管理値", value="", height=90)
            x_line = st.text_input("X通り", value="")
            y_line = st.text_input("Y通り", value="")
            reference_title = st.text_input("参考図タイトル", value="")
            extra_note = st.text_area("付加情報予備", value="", height=90)
            reference_upload = st.file_uploader("参考図画像", type=["jpg", "jpeg", "png"])
            shot_date_input = st.date_input("撮影年月日", value=datetime.now().date(), format="YYYY/MM/DD")
            contractor = st.text_input("施工者", placeholder="例: 山田工務店")
            observer = st.text_input("立会者", placeholder="例: 発注者")
            position = st.radio("合成位置", ["右下", "左下"], horizontal=True)
            board_scale = st.slider("黒板サイズ比率", min_value=0.30, max_value=1.00, value=0.55, step=0.02)
            add_btn = st.form_submit_button("追加", type="primary", width="stretch")

    data = {
        "project_name": normalize_value(project_name),
        "floor": normalize_value(floor),
        "location": normalize_value(location),
        "x_line": normalize_value(x_line),
        "y_line": normalize_value(y_line),
        "work_type": normalize_value(work_type),
        "category": normalize_value(category),
        "subcategory": normalize_value(subcategory),
        "control_value": normalize_value(control_value),
        "reference_title": normalize_value(reference_title),
        "extra_note": normalize_value(extra_note),
        "shot_date": shot_date_input.strftime("撮影年月日：%Y年%m月%d日"),
        "contractor": normalize_value(contractor),
        "observer": normalize_value(observer),
    }
    reference_image = Image.open(reference_upload).convert("RGB") if reference_upload is not None else None
    board_img = generate_blackboard(data, reference_image=reference_image)

    with col_preview:
        st.subheader("小黒板プレビュー")
        st.image(board_img, width="stretch")

    if add_btn:
        if upload is None:
            st.error("工事写真をアップロードしてください。")
            return

        photo = Image.open(upload).convert("RGB")
        composed = compose_blackboard(photo, board_img, position=position, ratio=board_scale)
        save_path = save_output(composed)
        upsert_project_name(project_name)

        st.success(f"合成画像を保存しました: {save_path}")
        st.image(composed, caption="合成結果", width="stretch")
        st.download_button(
            label="合成画像をダウンロード",
            data=to_bytes(composed),
            file_name=save_path.name,
            mime="image/png",
        )


if __name__ == "__main__":
    main()
