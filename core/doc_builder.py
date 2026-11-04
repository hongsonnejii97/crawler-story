"""
Word Document (.docx) Builder module.
Compiles all full, unsummarized chapter contents into a styled Microsoft Word document.
"""
import os
import re
from datetime import datetime
from typing import List, Optional

import docx
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .site_handlers.base import StoryInfo, ChapterContent

def sanitize_filename(name: str) -> str:
    """Sanitize string for safe Windows filename."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:100] if clean else "Truyen_Full"

class DocBuilder:
    def __init__(self, font_name: str = "Times New Roman", font_size: int = 12):
        self.font_name = font_name
        self.font_size = font_size
        self.doc = docx.Document()
        self._setup_document_styles()

    def _setup_document_styles(self):
        """Configure page margins and default typography styles."""
        # Page Margins (A4 standard: 1 inch = 2.54cm)
        for section in self.doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        # Base Normal style
        style_normal = self.doc.styles["Normal"]
        font = style_normal.font
        font.name = self.font_name
        font.size = Pt(self.font_size)
        font.color.rgb = RGBColor(0x1A, 0x20, 0x2C)  # Dark charcoal

    def build_story_document(
        self,
        story_info: StoryInfo,
        chapters: List[ChapterContent],
        output_dir: str = "output",
        include_toc: bool = True
    ) -> str:
        """
        Build the complete Word document and save to disk.
        Returns the absolute filepath of the generated document.
        """
        os.makedirs(output_dir, exist_ok=True)

        # 1. Cover / Title Page
        self._add_cover_page(story_info, len(chapters))

        # 2. Table of Contents (Optional)
        if include_toc and len(chapters) > 1:
            self._add_table_of_contents(chapters)

        # 3. Chapters Content (Full & Unsummarized)
        for i, chap in enumerate(chapters):
            self._add_chapter(chap, is_first=(i == 0 and not include_toc))

        # 4. Save Document
        safe_title = sanitize_filename(story_info.title)
        filename = f"{safe_title}_Full_{len(chapters)}_Chuong.docx"
        file_path = os.path.join(output_dir, filename)

        # Handle duplicate filenames
        counter = 1
        base_name, ext = os.path.splitext(filename)
        while os.path.exists(file_path):
            file_path = os.path.join(output_dir, f"{base_name}_{counter}{ext}")
            counter += 1

        self.doc.save(file_path)
        return os.path.abspath(file_path)

    def _add_cover_page(self, info: StoryInfo, total_chapters: int):
        """Create a book cover title page."""
        # Top spacing
        p_space = self.doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(40)

        # Title
        p_title = self.doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_title = p_title.add_run(info.title.upper())
        run_title.font.name = self.font_name
        run_title.font.size = Pt(26)
        run_title.font.bold = True
        run_title.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)  # Navy Blue
        p_title.paragraph_format.space_after = Pt(14)

        # Author
        p_author = self.doc.add_paragraph()
        p_author.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_author = p_author.add_run(f"Tác giả: {info.author}")
        run_author.font.name = self.font_name
        run_author.font.size = Pt(14)
        run_author.font.italic = True
        run_author.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)
        p_author.paragraph_format.space_after = Pt(24)

        # Decorative Divider
        p_div = self.doc.add_paragraph()
        p_div.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_div = p_div.add_run("❖  ❖  ❖")
        run_div.font.size = Pt(14)
        run_div.font.color.rgb = RGBColor(0xA0, 0xAE, 0xC0)
        p_div.paragraph_format.space_after = Pt(30)

        # Metadata Summary Box
        p_meta = self.doc.add_paragraph()
        p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        crawl_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        meta_text = (
            f"Tổng số chương: {total_chapters}\n"
            f"Nguồn truyện: {info.url}\n"
            f"Thời gian tạo file: {crawl_date}\n"
            f"Tình trạng: Toàn bộ nội dung đầy đủ (Không tóm tắt)"
        )
        run_meta = p_meta.add_run(meta_text)
        run_meta.font.size = Pt(10)
        run_meta.font.color.rgb = RGBColor(0x71, 0x80, 0x96)
        p_meta.paragraph_format.space_after = Pt(30)

        # Description / Synopsis (if available)
        if info.description:
            p_desc_hdr = self.doc.add_paragraph()
            p_desc_hdr.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run_hdr = p_desc_hdr.add_run("GIỚI THIỆU TRUYỆN")
            run_hdr.font.name = self.font_name
            run_hdr.font.size = Pt(12)
            run_hdr.font.bold = True
            run_hdr.font.color.rgb = RGBColor(0x2D, 0x37, 0x48)
            p_desc_hdr.paragraph_format.space_after = Pt(6)

            p_desc = self.doc.add_paragraph()
            p_desc.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            run_desc = p_desc.add_run(info.description)
            run_desc.font.name = self.font_name
            run_desc.font.size = Pt(11)
            run_desc.font.italic = True
            run_desc.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)
            p_desc.paragraph_format.left_indent = Inches(0.3)
            p_desc.paragraph_format.right_indent = Inches(0.3)
            p_desc.paragraph_format.line_spacing = 1.15

        # End of Cover Page
        self.doc.add_page_break()

    def _add_table_of_contents(self, chapters: List[ChapterContent]):
        """Add a formatted Table of Contents."""
        p_toc = self.doc.add_paragraph()
        p_toc.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_toc = p_toc.add_run("MỤC LỤC")
        run_toc.font.name = self.font_name
        run_toc.font.size = Pt(16)
        run_toc.font.bold = True
        run_toc.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)
        p_toc.paragraph_format.space_before = Pt(12)
        p_toc.paragraph_format.space_after = Pt(18)

        # List chapters (if too many, list title and chapter number)
        for i, chap in enumerate(chapters, start=1):
            p_item = self.doc.add_paragraph()
            p_item.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p_item.paragraph_format.space_after = Pt(3)
            p_item.paragraph_format.line_spacing = 1.15
            run_num = p_item.add_run(f"{i}. ")
            run_num.font.bold = True
            run_num.font.size = Pt(10.5)
            run_title = p_item.add_run(chap.title)
            run_title.font.size = Pt(10.5)

        self.doc.add_page_break()

    def _add_chapter(self, chap: ChapterContent, is_first: bool = False):
        """Append a chapter's title and its full unsummarized paragraphs."""
        if not is_first:
            self.doc.add_page_break()

        # Chapter Title
        p_title = self.doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_before = Pt(16)
        p_title.paragraph_format.space_after = Pt(18)

        run_title = p_title.add_run(chap.title)
        run_title.font.name = self.font_name
        run_title.font.size = Pt(15)
        run_title.font.bold = True
        run_title.font.color.rgb = RGBColor(0x1A, 0x36, 0x5D)

        # Paragraphs
        for para in chap.paragraphs:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(6)  # Professional 6pt spacing between paragraphs
            p.paragraph_format.line_spacing = 1.2
            p.paragraph_format.first_line_indent = Inches(0.3)  # Standard book indentation

            run = p.add_run(para)
            run.font.name = self.font_name
            run.font.size = Pt(self.font_size)
            run.font.color.rgb = RGBColor(0x2D, 0x37, 0x48)

