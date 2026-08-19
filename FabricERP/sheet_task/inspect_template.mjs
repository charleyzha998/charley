import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const templatePath = String.raw`H:\360MoveData\Users\Z\Desktop\公司业务\工作\LEJAAN\0201\Proforma Invoice PJ0201.xlsx`;
const input = await FileBlob.load(templatePath);
const wb = await SpreadsheetFile.importXlsx(input);

const sheetInfo = await wb.inspect({ kind: "sheet", include: "id,name" });
console.log("SHEETS\n" + sheetInfo.ndjson);
const rows = await wb.inspect({ kind: "table", range: "A1:Z60", maxChars: 20000, options: { maxResults: 500 } });
console.log("TABLE\n" + rows.ndjson);
const formulas = await wb.inspect({ kind: "formula", range: "A1:Z60", maxChars: 10000, options: { maxResults: 200 } });
console.log("FORMULAS\n" + formulas.ndjson);
const styles = await wb.inspect({ kind: "computedStyle", range: "A1:Z40", maxChars: 10000, options: { maxResults: 200 } });
console.log("STYLES\n" + styles.ndjson);

for (const s of wb.worksheets.items) {
  const blob = await wb.render({ sheetName: s.name, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(`C:/Users/Z/FabricERP/sheet_task/${s.name.replace(/[^a-z0-9_-]+/gi, "_")}.png`, new Uint8Array(await blob.arrayBuffer()));
}
