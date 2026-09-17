# DA62
Diamond DA62 Customized Checklists

Checklists for the Diamond DA62 G1000 panel.

You can import the json file using the "Garmin Checkset" program and generate a gcl to include in the panel.

Pull Requests are welcome, but need to be validated by the maintaners.

Feel free to fork this repo to create your own customized checklists

## Printable cards

`make_cards.py` renders the checklists into fold-in-half cards for printing and
laminating. Each PDF is a **single landscape US Letter page, printed on one side
only**: fold it down the middle with the print facing outwards and you get a
5.5" x 8.5" card with content on both faces.

| File | What is on it |
| --- | --- |
| `DA62-card-combined.pdf` | Normal Procedures on one face, Emergency Procedures on the other |
| `DA62-card-normal.pdf` | Normal Procedures spread over both faces (bigger type) |
| `DA62-card-emergency.pdf` | Emergency Procedures spread over both faces (bigger type) |

Print at 100% scale (no "fit to page"), single-sided, landscape.

To regenerate after editing `DA62checklists.json`:

```
pip install reportlab
python3 make_cards.py
```

The layout is computed from the content: the script picks the column count and
the largest type size that still fits, keeps every checklist whole within a
column, and balances the columns.
