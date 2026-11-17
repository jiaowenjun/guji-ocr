// Normalize spacing, circles and punctuation, then canonicalize without changing size boundaries.
import { formatSpaces } from "@/components/dataset/format-spaces";
import { formatCircles } from "@/components/dataset/format-circles";
import { formatDots } from "@/components/dataset/format-dots";
import { formatGj } from "@/parser/split-line";

export function formatDocument(text: string): {
  text: string;
  spaces: number;
  circles: number;
  dots: number;
} {
  const spaces = formatSpaces(text);
  const circles = formatCircles(spaces.text);
  const dots = formatDots(circles.text);
  return { text: formatGj(dots.text), spaces: spaces.count, circles: circles.count, dots: dots.count };
}
