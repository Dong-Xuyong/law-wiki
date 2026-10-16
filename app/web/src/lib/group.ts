import { SECTION_LABEL, SECTION_ORDER } from "./labels";
import type { Confidence, ReviewParagraph } from "../types";

const RANK: Record<Confidence, number> = { low: 0, medium: 1, high: 2 };

export type ParagraphGroup = {
  section: string;
  label: string;
  items: ReviewParagraph[];
};

export function groupParagraphs(
  paragraphs: ReviewParagraph[],
  uncertainFirst: boolean,
): ParagraphGroup[] {
  const known = new Set<string>(SECTION_ORDER);
  const groups: ParagraphGroup[] = SECTION_ORDER.map((section) => ({
    section,
    label: SECTION_LABEL[section],
    items: sortItems(
      paragraphs.filter((paragraph) => paragraph.section === section),
      uncertainFirst,
    ),
  })).filter((group) => group.items.length > 0);

  const extras = paragraphs.filter((paragraph) => !known.has(paragraph.section));
  if (extras.length > 0) {
    const bySection = new Map<string, ReviewParagraph[]>();
    for (const paragraph of extras) {
      const list = bySection.get(paragraph.section) ?? [];
      list.push(paragraph);
      bySection.set(paragraph.section, list);
    }
    for (const [section, items] of bySection) {
      groups.push({
        section,
        label: section || "Outros",
        items: sortItems(items, uncertainFirst),
      });
    }
  }

  return groups;
}

function sortItems(items: ReviewParagraph[], uncertainFirst: boolean): ReviewParagraph[] {
  return [...items].sort((a, b) => {
    if (uncertainFirst) {
      const byConfidence = RANK[a.confidence] - RANK[b.confidence];
      if (byConfidence !== 0) return byConfidence;
    }
    return a.index - b.index;
  });
}
