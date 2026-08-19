import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const templatePath = String.raw`H:\360MoveData\Users\Z\Desktop\公司业务\工作\LEJAAN\0201\Proforma Invoice PJ0201.xlsx`;
const outputDir = String.raw`C:\Users\Z\FabricERP\outputs\lejaan_pajama_sample_20260819`;
const outputPath = `${outputDir}/Proforma Invoice PJ0202.xlsx`;
await fs.mkdir(outputDir, { recursive: true });

const input = await FileBlob.load(templatePath);
const wb = await SpreadsheetFile.importXlsx(input);
const sheet = wb.worksheets.getItem("Sheet1");

// Header and customer/order metadata.
sheet.getRange("A4").values = [["Proforma Invoice"]];
sheet.getRange("A5").values = [["DATE: 2026/8/19"]];
sheet.getRange("N6").values = [["PJ0202"]];

// Two complete sample sets at USD 100 each; courier is explicitly free.
sheet.getRange("A11:O13").values = [
  [1, null, "SILK PAJAMA SET - LONG-SLEEVE SHIRT + LONG PANTS, SIZE S, BEIGE", null, null, null, 1, null, null, null, "USD", 100, "PER.SET", "USD", null],
  [2, null, "SILK PAJAMA SET - LONG-SLEEVE SHIRT + SHORT PANTS, SIZE M, ROSE", null, null, null, 1, null, null, null, "USD", 100, "PER.SET", "USD", null],
  [3, null, "COURIER SHIPPING (FREE OF CHARGE)", null, null, null, 1, null, null, null, "USD", 0, "PER.SET", "USD", null],
];
sheet.getRange("O11").formulas = [["=G11*L11"]];
sheet.getRange("O12").formulas = [["=G12*L12"]];
sheet.getRange("O13").formulas = [["=G13*L13"]];
sheet.getRange("O14").values = [[null]];
sheet.getRange("O15").formulas = [["=SUM(O11:O14)"]];
sheet.getRange("O16").values = [[0]];
sheet.getRange("O17").formulas = [["=O15-O16"]];
sheet.getRange("C11:C13").format.wrapText = true;
sheet.getRange("A11:O13").format.rowHeight = 30;

// Sample-order terms and notes.
sheet.getRange("D21").values = [["100% sample charge by TT before production."]];
sheet.getRange("D24").values = [["Courier"]];
sheet.getRange("C27").values = [["Two complete sample sets: European size S beige long-pants set; European size M rose short-pants set."]];
sheet.getRange("C28").values = [["Courier shipping is free of charge."]];
sheet.getRange("C27:C28").format.wrapText = true;

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);

// Verification output: key cells, formula errors, and a rendered preview.
const check = await wb.inspect({ kind: "table", range: "A4:O28", maxChars: 12000, options: { maxResults: 300 } });
console.log("CHECK\n" + check.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log("ERROR_SCAN\n" + errors.ndjson);
const preview = await wb.render({ sheetName: "Sheet1", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await preview.arrayBuffer()));
console.log(`OUTPUT\n${outputPath}`);
