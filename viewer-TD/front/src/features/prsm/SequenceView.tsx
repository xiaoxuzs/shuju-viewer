import type { ReactElement } from "react";
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { AnnotatedProtein, Cleavage, Residue } from "./parse";

interface Props {
  protein: AnnotatedProtein;
  className?: string;
  onCleavageClick?: (cleavage: Cleavage) => void;
}

/*
 * Port of topmsv/common/prsm_view/draw_prsm.ts.
 *
 * Everything is rendered into a single SVG so the geometry (letter spacing,
 * block gaps, row numbers, break-point brackets, mass-shift backgrounds and
 * annotations) stays pixel-faithful to the original TopPIC viewer instead
 * of being recreated with stacked HTML rows.
 *
 * Layout constants mirror `PrsmPara` defaults.
 */
const ROW_LENGTH = 30;
const BLOCK_LENGTH = 10;
const LETTER_WIDTH = 28;
const GAP_WIDTH = 20;
const ROW_HEIGHT = 40;
const TOP_MARGIN = 46;
const BOTTOM_MARGIN = 10;
const LEFT_MARGIN = 30;
const RIGHT_MARGIN = 30;
const EXTRA_PADDING = 20;
const NUMERICAL_WIDTH = 20;
const FONT_WIDTH = 12;
const FONT_HEIGHT = 18;
const LETTER_SIZE = 12;
const MIDDLE_MARGIN = 40;
const SKIP_LINE_HEIGHT = 40;
const MOD_ANNO_Y_SHIFTS = [-15, -30];
const BP_STROKE = "#1e90ff";
const MASS_SHIFT_COLORS: Record<string, string> = {
  variable: "#64E9EC",
  protein_variable: "#64E9EC",
  unexpected: "#ec6f64",
};

const SHOW_NUM = true;

function getX(pos: number, startPos: number): number {
  const num = pos - startPos;
  const posInRow = num % ROW_LENGTH;
  const gapNum = Math.floor(posInRow / BLOCK_LENGTH);
  let x = posInRow * LETTER_WIDTH + gapNum * GAP_WIDTH + LEFT_MARGIN;
  if (SHOW_NUM) x += NUMERICAL_WIDTH;
  return x;
}

function getY(pos: number, startPos: number): number {
  const row = Math.floor((pos - startPos) / ROW_LENGTH);
  return row * ROW_HEIGHT + TOP_MARGIN;
}

interface Annotation {
  leftPos: number;
  rightPos: number;
  annoText: string;
  type: string;
}

export function SequenceView({ protein, className, onCleavageClick }: Props) {
  const { residues, cleavages, massShifts, firstResiduePosition } = protein;
  const totalLen = residues.length;
  const localLast = Math.max(0, totalLen - 1);

  const {
    displayFirstPos,
    displayLastPos,
    rowNum,
    showStartSkipped,
    showEndSkipped,
    startSkippedInfo,
    endSkippedInfo,
  } = useMemo(() => {
    const dFirst = 0;
    let dLast = Math.ceil((localLast + 6) / ROW_LENGTH) * ROW_LENGTH - 1;
    if (dLast > localLast) dLast = localLast;
    const rn = Math.max(1, Math.ceil((dLast - dFirst + 1) / ROW_LENGTH));
    const ss = firstResiduePosition > 1;
    const se = false;
    return {
      displayFirstPos: dFirst,
      displayLastPos: dLast,
      rowNum: rn,
      showStartSkipped: ss,
      showEndSkipped: se,
      startSkippedInfo: ss
        ? `... ${firstResiduePosition - 1} amino acid residues are skipped at the N-terminus ... `
        : "",
      endSkippedInfo: se
        ? `... ${totalLen - 1 - dLast} amino acid residues are skipped at the C-terminus ... `
        : "",
    };
  }, [firstResiduePosition, localLast, totalLen]);

  const yShift = showStartSkipped ? MIDDLE_MARGIN : 0;

  // Fixed PTMs color their residue red; non-fixed mass shifts produce annotations.
  const fixedPtmPositions = useMemo(() => {
    const s = new Set<number>();
    for (const m of massShifts) {
      if (m.shiftType === "fixed") s.add(m.leftPosition);
    }
    return s;
  }, [massShifts]);

  const annotations: Annotation[] = useMemo(() => {
    const raw: Annotation[] = massShifts
      .filter((m) => m.shiftType !== "fixed")
      .map((m) => ({
        leftPos: m.leftPosition,
        rightPos: m.rightPosition,
        annoText: m.anno,
        type: m.shiftType,
      }))
      .sort((a, b) => a.leftPos - b.leftPos);

    // Merge consecutive annotations sharing the same range.
    const merged: Annotation[] = [];
    for (const a of raw) {
      const prev = merged[merged.length - 1];
      if (prev && prev.leftPos === a.leftPos && prev.rightPos === a.rightPos) {
        prev.annoText = `${prev.annoText};${a.annoText}`;
      } else {
        merged.push({ ...a });
      }
    }
    return merged;
  }, [massShifts]);

  const residueColor = (res: Residue): string => {
    if (fixedPtmPositions.has(res.position)) return "red";
    return "black";
  };

  // SVG canvas size (mirrors `PrsmPara.getSvgSize`).
  const blockNum = ROW_LENGTH / BLOCK_LENGTH - 1;
  let width =
    LETTER_WIDTH * (ROW_LENGTH - 1) + blockNum * GAP_WIDTH + RIGHT_MARGIN + LEFT_MARGIN + EXTRA_PADDING;
  if (SHOW_NUM) width += NUMERICAL_WIDTH * 2;
  let height = ROW_HEIGHT * (rowNum - 1) + LETTER_SIZE + BOTTOM_MARGIN + TOP_MARGIN;
  if (showStartSkipped) height += SKIP_LINE_HEIGHT;
  if (showEndSkipped) height += SKIP_LINE_HEIGHT;

  // Right-number X: mirrors `PrsmPara.getRightNumCoordinates`.
  const rightNumX =
    LEFT_MARGIN +
    NUMERICAL_WIDTH +
    (ROW_LENGTH - 1) * LETTER_WIDTH +
    (ROW_LENGTH / BLOCK_LENGTH - 1) * GAP_WIDTH +
    NUMERICAL_WIDTH +
    FONT_WIDTH;

  // Pre-compute annotation Y-shifts with the same "alternate on overlap" rule
  // used in the original `addAnnos`.
  const annoYShiftIdx: number[] = useMemo(() => {
    const out: number[] = [];
    let prevIdx = 0;
    for (let i = 0; i < annotations.length; i++) {
      const cur = annotations[i];
      const [x1, y1] = [getX(cur.leftPos, displayFirstPos), getY(cur.leftPos, displayFirstPos)];
      let overlap = false;
      if (i > 0) {
        const prev = annotations[i - 1];
        const [x2, y2] = [
          getX(Math.floor(prev.leftPos), displayFirstPos),
          getY(Math.floor(prev.leftPos), displayFirstPos),
        ];
        const annoLen = prev.annoText.length * (FONT_WIDTH - 2);
        if (y1 === y2 && x1 - x2 < annoLen) overlap = true;
      }
      const idx = overlap ? (prevIdx + 1) % 2 : 0;
      out.push(idx);
      prevIdx = idx;
    }
    return out;
  }, [annotations, displayFirstPos]);

  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <svg
        className="mx-auto block"
        width={width}
        height={height}
        fontFamily="FreeMono, Consolas, 'Courier New', monospace"
        fontSize={16}
        style={{ background: "white" }}
      >
        {showStartSkipped && (
          <text
            x={LEFT_MARGIN}
            y={TOP_MARGIN}
            fill="black"
            fontSize={15}
          >
            {startSkippedInfo}
          </text>
        )}

        {/* Mass-shift background rectangles (drawn first so letters sit on top) */}
        <g>
          {annotations.flatMap((anno, annoIdx) => {
            const { leftPos, rightPos, type } = anno;
            const startRow = Math.floor((leftPos - displayFirstPos) / ROW_LENGTH);
            const endRow = Math.floor((rightPos - 1 - displayFirstPos) / ROW_LENGTH);
            const rects: ReactElement[] = [];
            for (let j = startRow; j <= endRow; j++) {
              let rowLeft = displayFirstPos + j * ROW_LENGTH;
              let rowRight = rowLeft + ROW_LENGTH - 1;
              if (j === startRow) rowLeft = leftPos;
              if (j === endRow) rowRight = rightPos - 1;
              if (rowLeft > displayLastPos || rowRight < displayFirstPos) continue;
              const x1 = getX(rowLeft, displayFirstPos);
              const x2 = getX(rowRight, displayFirstPos);
              const y1 = getY(rowLeft, displayFirstPos) + yShift;
              rects.push(
                <rect
                  key={`bg-${annoIdx}-${j}`}
                  x={x1 - FONT_WIDTH * 0.1}
                  y={y1 - FONT_HEIGHT * 0.7}
                  width={x2 - x1 + FONT_WIDTH}
                  height={FONT_HEIGHT}
                  fill={MASS_SHIFT_COLORS[type] ?? "#64E9EC"}
                  fillOpacity={0.4}
                />,
              );
            }
            return rects;
          })}
        </g>

        {/* Mass-shift text annotations above residues */}
        <g>
          {annotations.map((anno, i) => {
            const x = getX(anno.leftPos, displayFirstPos);
            const y = getY(anno.leftPos, displayFirstPos) + MOD_ANNO_Y_SHIFTS[annoYShiftIdx[i] ?? 0] + yShift;
            return (
              <text key={`anno-${i}`} x={x} y={y} fill="black" fontSize={15}>
                {anno.annoText}
              </text>
            );
          })}
        </g>

        {/* Position numbers on both sides of each row */}
        <g>
          {Array.from({ length: rowNum }, (_, i) => {
            const leftPos = displayFirstPos + i * ROW_LENGTH;
            const [lx, ly] = [LEFT_MARGIN, getY(leftPos, displayFirstPos) + yShift];
            const leftText = leftPos + 1;
            let rightPos = leftPos + ROW_LENGTH - 1;
            if (rightPos > displayLastPos) rightPos = displayLastPos;
            const ry = getY(rightPos, displayFirstPos) + yShift;
            const rightText = rightPos + 1;
            return (
              <g key={`num-${i}`}>
                <text x={lx} y={ly} fill="black" textAnchor="end">
                  {leftText}
                </text>
                <text x={rightNumX} y={ry} fill="black" textAnchor="start">
                  {rightText}
                </text>
              </g>
            );
          })}
        </g>

        {/* Amino-acid letters */}
        <g>
          {residues.map((r) => {
            if (r.position < displayFirstPos || r.position > displayLastPos) return null;
            const x = getX(r.position, displayFirstPos);
            const y = getY(r.position, displayFirstPos) + yShift;
            return (
              <text key={`aa-${r.position}`} x={x} y={y} fill={residueColor(r)}>
                {r.acid}
              </text>
            );
          })}
        </g>

        {/* Start / end boundary symbols for the matched form region */}
        {firstResiduePosition > 1 && (
          <BoundarySymbol
            kind="start"
            pos={0}
            startPos={displayFirstPos}
            yShift={yShift}
          />
        )}
        {showEndSkipped && (
          <BoundarySymbol
            kind="end"
            pos={localLast}
            startPos={displayFirstPos}
            yShift={yShift}
          />
        )}

        {/* Break points (N/C ion cleavage brackets) */}
        <g>
          {cleavages.map((bp) => {
            if (!bp.existNIon && !bp.existCIon) return null;
            const anchorPos = bp.position - 1;
            if (anchorPos < displayFirstPos || anchorPos > displayLastPos) return null;
            const x = getX(anchorPos, displayFirstPos) + LETTER_WIDTH / 2;
            const y = getY(anchorPos, displayFirstPos) + yShift;

            let points: string;
            if (bp.existNIon && !bp.existCIon) {
              points = `${x - 2},${y - 13} ${x + 4},${y - 11} ${x + 4},${y + 2}`;
            } else if (!bp.existNIon && bp.existCIon) {
              points = `${x + 4},${y - 11} ${x + 4},${y + 2} ${x + 10},${y + 5}`;
            } else {
              points = `${x - 2},${y - 13} ${x + 4},${y - 11} ${x + 4},${y + 2} ${x + 10},${y + 5}`;
            }

            return (
              <g key={`bp-${bp.position}`}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={BP_STROKE}
                  strokeWidth={1}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {/* Transparent hit target so consumers can hook into clicks */}
                <rect
                  x={x}
                  y={y - 14}
                  width={13}
                  height={23}
                  fill="transparent"
                  style={{ cursor: onCleavageClick ? "pointer" : "default" }}
                  onClick={onCleavageClick ? () => onCleavageClick(bp) : undefined}
                >
                  <title>
                    {`cleavage ${bp.position}${bp.existNIon ? " · N-ion" : ""}${bp.existCIon ? " · C-ion" : ""}`}
                  </title>
                </rect>
              </g>
            );
          })}
        </g>

        {showEndSkipped && (
          <text
            x={LEFT_MARGIN}
            y={getY(displayLastPos + 1, displayFirstPos) + yShift}
            fill="black"
            fontSize={15}
          >
            {endSkippedInfo}
          </text>
        )}
      </svg>
    </div>
  );
}

function BoundarySymbol({
  kind,
  pos,
  startPos,
  yShift,
}: {
  kind: "start" | "end";
  pos: number;
  startPos: number;
  yShift: number;
}) {
  const [baseX, baseY] = [getX(pos, startPos), getY(pos, startPos) + yShift];
  if (kind === "start") {
    const x = baseX - LETTER_WIDTH / 2;
    const y = baseY;
    const points = `${x},${y + 2} ${x + 5},${y + 2} ${x + 5},${y - 12} ${x},${y - 12}`;
    return (
      <polyline
        points={points}
        fill="none"
        stroke="red"
        strokeWidth={1.3}
      />
    );
  }
  const x = baseX + LETTER_WIDTH / 2;
  const y = baseY;
  const points = `${x + 7},${y - 12} ${x + 2},${y - 12} ${x + 2},${y + 2} ${x + 7},${y + 2}`;
  return (
    <polyline
      points={points}
      fill="none"
      stroke="red"
      strokeWidth={1.3}
    />
  );
}
