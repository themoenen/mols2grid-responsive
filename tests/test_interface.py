import json
import os
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import geckodriver_autoinstaller
import imagehash
import pytest
from flaky import flaky
from rdkit import Chem
from rdkit import __version__ as rdkit_version
from rdkit.Chem import AllChem
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

import mols2grid
from mols2grid.select import register
from mols2grid.utils import env

from .webdriver_utils import FirefoxDriver

geckodriver_autoinstaller.install()
pytestmark = pytest.mark.webdriver
GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS")
HEADLESS = True
PAGE_LOAD_TIMEOUT = 10


def determine_scope(fixture_name, config):
    if GITHUB_ACTIONS:
        return "function"
    return "module"


def get_grid(df, **kwargs):
    kwargs.setdefault("mol_col", "mol")
    return mols2grid.MolGrid(df, **kwargs)


def get_doc(grid, kwargs):
    html = grid.render(**kwargs)
    html = b64encode(html.encode()).decode()
    return "data:text/html;base64,{}".format(html)


@pytest.fixture(scope=determine_scope)
def driver():
    options = webdriver.FirefoxOptions()
    options.headless = True if GITHUB_ACTIONS else HEADLESS
    driver = FirefoxDriver(options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    yield driver
    driver.quit()


@pytest.fixture(scope="module")
def html_doc(grid):
    return get_doc(grid, dict(n_items_per_page=5, subset=["_Name", "img"]))


# make sure non-parametrized test is ran first
@pytest.mark.order(1)
def test_no_subset_all_visible(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"tooltip": [], "selection": False})
    driver.get(doc)
    columns = set(grid.dataframe.columns.drop(["mol", "mols2grid-id"]).to_list())
    cell = driver.find_by_css_selector("#mols2grid .m2g-cell")
    data_el = cell.find_elements_by_class_name("data")
    classes = [
        c.replace("data-", "").replace("-display", "")
        for x in data_el
        for c in x.get_attribute("class").split(" ")
        if c.startswith("data-")
    ]
    classes = set(classes)
    assert classes == columns


def test_smiles_hidden(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-SMILES")
    assert not el.is_displayed()


@pytest.mark.parametrize("page", [1, 2, 3])
def test_page_click(driver: FirefoxDriver, grid, page):
    doc = get_doc(grid, dict(subset=["img", "_Name"], n_items_per_page=9))
    driver.get(doc)
    for i in range(2, page + 1):
        driver.wait_for_img_load()
        next_page = driver.find_by_css_selector(f'a.page-link[data-i="{i}"]')
        next_page.click()
    first_cell = driver.find_by_class_name("m2g-cell")
    mols2grid_id = 9 * (page - 1)
    name = first_cell.find_element_by_class_name("data-_Name")
    ref = grid.dataframe.iloc[mols2grid_id]
    assert name.text == ref["_Name"]


@pytest.mark.parametrize(
    ["name", "css_prop", "value", "expected"],
    [
        ("gap", "margin-top", 20, "20px"),
        ("border", "border-top-width", "3px solid", "3px"),
        ("border", "border-top-style", "1px dashed", "dashed"),
        ("border", "border-top-color", "1px solid blue", "rgb(0, 0, 255)"),
        ("fontsize", "font-size", "16pt", "21.3333px"),
        ("fontfamily", "font-family", "Consolas", "Consolas"),
        ("textalign", "text-align", "right", "right"),
        (
            "custom_css",
            "background-color",
            ".m2g-cell { background-color: black; }",
            "rgb(0, 0, 0)",
        ),
    ],
)
def test_css_properties(driver: FirefoxDriver, grid, name, css_prop, value, expected):
    doc = get_doc(grid, {name: value})
    driver.get(doc)
    computed = driver.execute_script(
        f"return getComputedStyle(document.querySelector('#mols2grid .m2g-cell')).getPropertyValue({css_prop!r});"
    )
    assert computed == expected


def test_text_search(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.text_search("iodopropane")
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-SMILES")
    assert el.get_attribute("innerHTML") == "CC(I)C"


def test_text_search_regex_chars(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.text_search("1-pentene")
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-SMILES")
    assert el.get_attribute("innerHTML") == "CCCC=C"


@flaky(max_runs=3, min_passes=1)
def test_smarts_search(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.substructure_query("CC(I)C")
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "2-iodopropane"


def test_selection_click(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.find_clickable(By.CSS_SELECTOR, "input[type='checkbox']").click()
    sel = driver.wait_for_selection(is_empty=False)
    assert sel == {0: "CCC(C)CC"}
    register._clear()


def test_export_csv(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.find_clickable(By.CSS_SELECTOR, "input[type='checkbox']").click()
    driver.wait_for_selection(is_empty=False)
    driver.sort_grid("_Name")
    now = datetime.now(tz=timezone.utc)
    driver.grid_action("save-csv")
    csv_files = sorted(
        (Path.home() / "Downloads").glob("selection*.csv"),
        key=lambda x: x.stat().st_mtime,
    )
    csv_file = csv_files[-1]
    file_mtime = datetime.fromtimestamp(csv_file.stat().st_mtime, tz=timezone.utc)
    assert (file_mtime - now).seconds < 1, "Could not find recent selection file"
    content = csv_file.read_text()
    assert content == "index\t_Name\tSMILES\n0\t3-methylpentane\tCCC(C)CC\n"
    csv_file.unlink()
    register._clear()


def test_selection_with_cache_check_and_uncheck(driver: FirefoxDriver, df):
    register._init_grid("cached_sel")
    event = SimpleNamespace(new='{0: "CCC(C)CC"}')
    register.selection_updated("cached_sel", event)
    grid = get_grid(df, name="cached_sel", cache_selection=True)
    doc = get_doc(grid, {})
    driver.get(doc)
    driver.wait_for_img_load()
    sel = driver.wait_for_selection(is_empty=False)
    assert sel == {0: "CCC(C)CC"}
    driver.find_clickable(By.CSS_SELECTOR, "input[type='checkbox']").click()
    empty_sel = driver.wait_for_selection(is_empty=True)
    assert empty_sel is True
    register._clear()


def test_selection_check_uncheck_invert(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    # search
    driver.text_search("iodopropane")
    # check all
    driver.grid_action("select-all")
    sel = driver.wait_for_selection(is_empty=False)
    assert len(sel) == 30
    # uncheck all
    driver.grid_action("unselect-all")
    empty_sel = driver.wait_for_selection(is_empty=True)
    assert empty_sel is True
    # check matching
    driver.grid_action("select-matching")
    sel = driver.wait_for_selection(is_empty=False)
    assert sel == {27: "CC(I)C"}
    # invert
    driver.grid_action("invert")
    sel = driver.wait_for_selection(is_empty=False)
    assert len(sel) == 29
    register._clear()


@pytest.mark.parametrize("prerender", [True, False])
def test_image_size(driver: FirefoxDriver, df, prerender):
    grid = get_grid(df, size=(100, 100), prerender=prerender)
    doc = get_doc(
        grid,
        {
            "selection": False,
            "border": "0",
            "substruct_highlight": False,
            "n_items_per_page": 1,
        },
    )
    driver.get(doc)
    if not prerender:
        driver.wait_for_img_load()
    img = driver.find_by_css_selector("#mols2grid .m2g-cell .data-img *")
    assert img.size == {"height": 100.0, "width": 100.0}


def test_image_use_coords(driver: FirefoxDriver, df):
    mols = df["mol"][:1]
    AllChem.EmbedMolecule(mols[0], randomSeed=0xF00D)
    grid = mols2grid.MolGrid.from_mols(
        mols, use_coords=True, prerender=True, useSVG=False
    )
    doc = get_doc(grid, {"substruct_highlight": False})
    driver.get(doc)
    hash_ = driver.get_png_hash()
    diff = hash_ - imagehash.hex_to_hash(
        "ffffffffff7fff7ffe7ffe7ffe7ffe7ffe7fe07fc33f0fbc3f80ffc7ffffffff"
    )
    assert diff <= 2


@pytest.mark.parametrize(
    ["coordGen", "prerender", "expected"],
    [
        (
            True,
            True,
            "fffffffffffffe7ffe7ffe7ffe7ffe7ffe7f3e7c8811c183e7e7ffffffffffff",
        ),
        (
            True,
            False,
            "fffffffffffffe7ffe7ffe7ffe7ffe7ffe7f3e7c8811c183e7e7ffffffffffff",
        ),
        (
            False,
            True,
            "ffffffff03fcf9fcfdf9fcf9fcfbfe03fe07fcfffcfffdfff9fffbffffffffff",
        ),
        (
            False,
            False,
            "ffffffff03fcf9fcfdf9fcf9fcfbfe03fe07fcfffcfffdfff9fffbffffffffff",
        ),
    ],
)
def test_coordgen(driver: FirefoxDriver, mols, coordGen, prerender, expected):
    useSVG = not prerender
    grid = mols2grid.MolGrid.from_mols(
        mols, coordGen=coordGen, prerender=prerender, useSVG=useSVG, use_coords=False
    )
    doc = get_doc(grid, {"substruct_highlight": False})
    driver.get(doc)
    if not prerender:
        driver.wait_for_img_load()
    if useSVG:
        hash_ = driver.get_svg_hash()
    else:
        hash_ = driver.get_png_hash()
    assert str(hash_) == expected


@pytest.mark.parametrize(
    ["removeHs", "prerender", "expected"],
    [
        (
            True,
            True,
            "fffffffffffffe7ffe7ffe7ffe7ffe7ffe7f3e7c8811c183e7e7ffffffffffff",
        ),
        (
            False,
            True,
            (
                "ffffff7fff3fffbff907e02fe13ff80fcbafe33fe033cb07fa4ffa4fff97ffd7"
                if rdkit_version == "2020.03.1"
                else "ff7ffe1ff91ffd3ff00ff0cffcbff0bff00ffd3fe1bff887f29ff30fff6fff7f"
            ),
        ),
        (
            True,
            False,
            "fffffffffffffe7ffe7ffe7ffe7ffe7ffe7f3e7c8811c183e7e7ffffffffffff",
        ),
        (
            False,
            False,
            "ff7ffe1ff91ffd3ff00ff0cffcbff0bff00ffd3fe1bff887f29ff30fff6fff7f",
        ),
    ],
)
def test_removeHs(driver: FirefoxDriver, df, removeHs, prerender, expected):
    useSVG = not prerender
    mol = df["mol"][0]
    mol.ClearProp("SMILES")
    mols = [Chem.AddHs(mol)]
    grid = mols2grid.MolGrid.from_mols(
        mols, removeHs=removeHs, prerender=prerender, useSVG=useSVG, use_coords=False
    )
    doc = get_doc(grid, {"n_items_per_page": 5, "substruct_highlight": False})
    driver.get(doc)
    if not prerender:
        driver.wait_for_img_load()
    if useSVG:
        hash_ = driver.get_svg_hash()
    else:
        hash_ = driver.get_png_hash()
    if expected == "":
        raise AssertionError(str(hash_))
    diff = hash_ - imagehash.hex_to_hash(expected)
    assert diff <= 1


@pytest.mark.parametrize(
    ["kwargs", "expected"],
    [
        (
            dict(addAtomIndices=True),
            "ffffffffff7ffe3ffe7ffefffeff3e7f3e791830c184e7cfe7cff7cfffffffff",
        ),
        (
            dict(fixedBondLength=10),
            "fffffffffffffffffffffffffe7ffe7ff81ffc3fffffffffffffffffffffffff",
        ),
        (
            dict(atomColourPalette={6: (0, 0.8, 0.8)}),
            "fffffffffffffffffe7ffe7ffe7ffe7ffe7f3e7c8819c183e7e7ffffffffffff",
        ),
        (
            dict(legend="foo"),
            "fffffffffffffe7ffe7ffe7ffe7ffe7f3e7c1818c183e7e7fffffffffe7ffe7f",
        ),
    ],
)
def test_moldrawoptions(driver: FirefoxDriver, df, kwargs, expected):
    grid = get_grid(df, **kwargs)
    doc = get_doc(grid, dict(n_items_per_page=1, subset=["img"]))
    driver.get(doc)
    driver.wait_for_img_load()
    hash_ = driver.get_svg_hash()
    assert str(hash_) == expected


def test_hover_color(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"hover_color": "red"})
    driver.get(doc)
    (
        ActionChains(driver)
        .move_to_element(driver.find_by_css_selector("#mols2grid .m2g-cell"))
        .pause(0.2)
        .perform()
    )
    color = driver.execute_script(
        f"return getComputedStyle(document.querySelector('#mols2grid .m2g-cell')).getPropertyValue('background-color');"
    )
    assert color == "rgb(255, 0, 0)"


@flaky(max_runs=3, min_passes=1)
def test_tooltip(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"tooltip": ["_Name"]})
    driver.get(doc)
    driver.wait_for_img_load()
    (
        ActionChains(driver)
        .move_to_element(
            driver.find_by_css_selector("#mols2grid .m2g-cell .data-img *")
        )
        .perform()
    )
    tooltip = driver.find_by_css_selector('div.popover[role="tooltip"]')
    el = tooltip.find_element_by_class_name("popover-body")
    assert el.get_attribute("innerHTML") == "<strong>_Name</strong>: 3-methylpentane"


@flaky(max_runs=3, min_passes=1)
def test_tooltip_trigger(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"tooltip": ["_Name"], "tooltip_trigger": "click"})
    driver.get(doc)
    driver.wait_for_img_load()
    (
        ActionChains(driver)
        .move_to_element(
            driver.find_by_css_selector("#mols2grid .m2g-cell .data-img *")
        )
        .perform()
    )
    with pytest.raises(NoSuchElementException):
        driver.find_element_by_css_selector('div.popover[role="tooltip"]')
    driver.find_clickable(By.CSS_SELECTOR, "#mols2grid .m2g-cell .data-img *").click()
    tooltip = driver.find_by_css_selector('div.popover[role="tooltip"]')
    el = tooltip.find_element_by_class_name("popover-body")
    assert el.get_attribute("innerHTML") == "<strong>_Name</strong>: 3-methylpentane"


@flaky(max_runs=3, min_passes=1)
def test_tooltip_fmt(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"tooltip": ["_Name"], "tooltip_fmt": "<em>{value}</em>"})
    driver.get(doc)
    driver.wait_for_img_load()
    tooltip = driver.get_tooltip_content()
    assert tooltip == "<em>3-methylpentane</em>"


def test_tooltip_not_in_subset(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"tooltip": ["_Name"], "subset": ["ID", "img"]})
    driver.get(doc)
    driver.wait_for_img_load()
    tooltip = driver.get_tooltip_content()
    assert tooltip == "<strong>_Name</strong>: 3-methylpentane"


@flaky(max_runs=3, min_passes=1)
def test_style(driver: FirefoxDriver, grid):
    doc = get_doc(
        grid,
        {
            "tooltip": ["_Name"],
            "style": {
                "__all__": lambda x: "color: red",
                "_Name": lambda x: "color: blue",
            },
        },
    )
    driver.get(doc)
    driver.wait_for_img_load()
    el = driver.find_by_css_selector("#mols2grid .m2g-cell")
    assert el.value_of_css_property("color") == "rgb(255, 0, 0)"
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.value_of_css_property("color") == "rgb(0, 0, 255)"
    tooltip = driver.get_tooltip_content()
    assert (
        tooltip
        == '<strong>_Name</strong>: <span style="color: blue">3-methylpentane</span>'
    )


@flaky(max_runs=3, min_passes=1)
def test_transform(driver: FirefoxDriver, grid):
    doc = get_doc(
        grid, {"tooltip": ["_Name"], "transform": {"_Name": lambda x: x.upper()}}
    )
    driver.get(doc)
    name = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert name.text == "3-METHYLPENTANE"
    driver.wait_for_img_load()
    tooltip = driver.get_tooltip_content(pause=0.5)
    assert tooltip == "<strong>_Name</strong>: 3-METHYLPENTANE"


@flaky(max_runs=3, min_passes=1)
def test_transform_style_tooltip(driver: FirefoxDriver, grid):
    doc = get_doc(
        grid,
        {
            "tooltip": ["_Name"],
            "transform": {"_Name": lambda x: "foo"},
            "style": {
                "__all__": lambda x: "background-color: red",
                "_Name": lambda x: "color: green" if x == "foo" else "color: blue",
            },
        },
    )
    driver.get(doc)
    driver.wait_for_img_load()
    cell = driver.find_by_css_selector("#mols2grid .m2g-cell")
    assert cell.value_of_css_property("background-color") == "rgb(255, 0, 0)"
    name = cell.find_element_by_class_name("data-_Name")
    assert name.text == "foo"
    tooltip = driver.get_tooltip_content(pause=0.5)
    assert tooltip == '<strong>_Name</strong>: <span style="color: blue">foo</span>'


@pytest.mark.parametrize("selection", [True, False])
def test_callback_js(driver: FirefoxDriver, grid, selection):
    doc = get_doc(
        grid,
        {
            "subset": ["img", "_Name"],
            "callback": "$('#mols2grid .m2g-cell .data-_Name').html('foo')",
            "selection": selection,
        },
    )
    driver.get(doc)
    driver.wait_for_img_load()
    driver.trigger_callback()
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "foo"


def test_sort_by(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"subset": ["img", "_Name"], "sort_by": "_Name"})
    driver.get(doc)
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "1,1,2,2-tetrachloroethane"


def test_sort_button(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.sort_grid("_Name")
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "1,1,2,2-tetrachloroethane"
    driver.invert_sort()
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "tetrachloromethane"


@pytest.mark.parametrize(
    ["substruct_highlight", "expected"],
    [
        (True, "fffffe7ffc3ffc3ffe7ffe7ffe7ffe7ffe7ffc3ff81fc003c3c3c7e3c7e3eff7"),
        (False, "fe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffc3ff99fe3c7c7e3cff3"),
    ],
)
def test_substruct_highlight(
    driver: FirefoxDriver, grid, substruct_highlight, expected
):
    doc = get_doc(
        grid, {"n_items_per_page": 5, "substruct_highlight": substruct_highlight}
    )
    driver.get(doc)
    driver.wait_for_img_load()
    driver.substructure_query("CC(I)C")
    hash_ = driver.get_svg_hash()
    assert str(hash_) == expected


def test_substruct_clear_removes_highlight(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"n_items_per_page": 5, "substruct_highlight": True})
    driver.get(doc)
    driver.wait_for_img_load()
    driver.substructure_query("C")
    hash_hl = driver.get_svg_hash()
    driver.clear_search()
    hash_ = driver.get_svg_hash()
    assert hash_ != hash_hl
    assert (
        str(hash_) == "fffffffffffffe7ffe7ffe7ffe7ffe7ffe7f3e7c8811c183e7e7ffffffffffff"
    )


def test_smarts_to_text_search_removes_highlight(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"n_items_per_page": 5, "substruct_highlight": True})
    driver.get(doc)
    driver.wait_for_img_load()
    driver.substructure_query("I")
    hash_hl = driver.get_svg_hash()
    driver.text_search("odopropane")
    hash_ = driver.get_svg_hash()
    assert hash_ != hash_hl
    assert (
        str(hash_) == "fe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffe7ffc3ff99fe3c7c7e3cff3"
    )


def test_filter(driver: FirefoxDriver, grid):
    doc = get_doc(
        grid,
        {
            "subset": ["img", "_Name"],
        },
    )
    driver.get(doc)
    mask = grid.dataframe["_Name"].str.contains("iodopropane")
    filter_code = env.get_template("js/filter.js").render(
        grid_id=grid._grid_id, mask=json.dumps(mask.tolist())
    )
    driver.wait_for_img_load()
    driver.execute_script(filter_code)
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-_Name")
    assert el.text == "2-iodopropane"


def test_subset_gives_rows_order(driver: FirefoxDriver, grid):
    subset = ["_Name", "ID"]
    doc = get_doc(grid, {"subset": subset, "n_items_per_page": 5})
    driver.get(doc)
    driver.wait_for_img_load()
    cell = driver.find_by_css_selector("#mols2grid .m2g-cell")
    elements = cell.find_elements_by_class_name("data")
    i = 0
    for el in elements:
        class_list = el.get_attribute("class").split()
        name = [x.replace("data-", "") for x in class_list if x.startswith("data-")][0]
        if name in {"img", "SMILES"}:
            continue
        assert name == subset[i]
        i += 1
    # smiles should always be there, and last
    assert name == "SMILES"
    assert el.value_of_css_property("display") == "none"


def test_colname_with_spaces(driver: FirefoxDriver, df):
    df = df.rename(columns={"SMILES": "Molecule", "_Name": "Molecule name"}).drop(
        columns="mol"
    )
    grid = mols2grid.MolGrid(df, smiles_col="Molecule")
    doc = get_doc(
        grid,
        dict(subset=["Molecule name", "img"], tooltip=["Molecule"], n_items_per_page=5),
    )
    driver.get(doc)
    driver.wait_for_img_load()
    el = driver.find_by_css_selector("#mols2grid .m2g-cell .data-Molecule-name")
    assert el.text == "3-methylpentane"


@flaky(max_runs=3, min_passes=1)
def test_custom_header(driver: FirefoxDriver, grid):
    doc = get_doc(
        grid,
        {
            "subset": ["img"],
            "custom_header": '<script src="https://unpkg.com/@rdkit/rdkit@2021.9.2/Code/MinimalLib/dist/RDKit_minimal.js"></script>',
            "n_items_per_page": 5,
        },
    )
    driver.get(doc)
    driver.wait_for_img_load()
    val = driver.execute_script("return RDKit.version();")
    assert val == "2021.09.2"


def test_static_template(driver: FirefoxDriver, sdf_path):
    df = mols2grid.sdf_to_dataframe(sdf_path)[:15]
    grid = mols2grid.MolGrid(df, mol_col="mol", prerender=True)
    doc = get_doc(
        grid,
        dict(
            template="static",
            subset=["mols2grid-id", "img"],
            tooltip=["_Name"],
            sort_by="_Name",
            tooltip_trigger="hover",
        ),
    )
    driver.get(doc)
    el = driver.find_by_css_selector("#mols2grid td.col-0")
    assert el.find_element_by_class_name("data-mols2grid-id").text == "8"
    tooltip = driver.get_tooltip_content(selector=".m2g-cell-0")
    assert tooltip == "<strong>_Name</strong>: 1,3,5-trimethylbenzene"
    hash_ = driver.get_svg_hash("#mols2grid td .data-img")
    diff = hash_ - imagehash.hex_to_hash(
        "fffffe7ffe7ffe7ffe7ffe7ffc3ff10ff3cff3cff3cff3cff38fe1078c319e79"
    )
    assert diff <= 1


def test_default_subset_tooltip(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"n_items_per_page": 5})
    driver.get(doc)
    driver.wait_for_img_load()
    expected_subset = ["img"]
    expected_tooltip = [
        x
        for x in grid.dataframe.columns.drop(["mol", "mols2grid-id"]).to_list()
        if x not in expected_subset
    ]
    cell = driver.find_by_css_selector("#mols2grid .m2g-cell")
    data_elements = cell.find_elements_by_class_name("data")
    subset = [
        c.replace("data-", "").replace("-display", "")
        for x in data_elements
        for c in x.get_attribute("class").split(" ")
        if c.startswith("data-") and not x.get_attribute("style")
    ]
    assert subset == expected_subset
    tooltip = [
        c.replace("data-", "").replace("-display", "")
        for x in data_elements
        for c in x.get_attribute("class").split(" ")
        if c.startswith("data-") and x.get_attribute("style") == "display: none;"
    ]
    assert tooltip == expected_tooltip


def test_multi_highlight(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.substructure_query("Br")
    hash_ = driver.get_svg_hash()
    assert (
        str(hash_) == "ffffffff8fff87ff003f079f8fdfffcfffefffe1ffe1ffe0ffe1fff1ffffffff"
    )


def test_single_highlight(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"single_highlight": True})
    driver.get(doc)
    driver.wait_for_img_load()
    driver.substructure_query("Br")
    hash_ = driver.get_svg_hash()
    assert (
        str(hash_) == "ffffffff8fff87ff003f001f87cfcfcfffefffe7fff3fff0fff1fff1ffffffff"
    )


def test_mol_depiction_aligned_to_query(driver: FirefoxDriver, html_doc):
    driver.get(html_doc)
    driver.wait_for_img_load()
    driver.substructure_query("CCCBr")
    images = list(driver.get_imgs_from_svgs())
    for img, expected in zip(
        images,
        [
            "fffffffffcf9f8f8f0708001070f0f8f9f9fffdfffdfff9fff8fff8fffffffff",
            "fffffffffffffff9fff9fff9fff9f8f9f8f0d0018003078f8f8fffffffffffff",
        ],
    ):
        hash_ = imagehash.average_hash(img, hash_size=16)
        assert str(hash_) == expected


def test_highlight_with_hydrogens(driver: FirefoxDriver, df):
    mols = []
    for mol in df["mol"][25:]:
        m = Chem.AddHs(mol)
        m.ClearProp("SMILES")
        mols.append(m)
    grid = mols2grid.MolGrid.from_mols(mols, removeHs=False)
    doc = get_doc(grid, dict(substruct_highlight=True, single_highlight=False))
    driver.get(doc)
    driver.wait_for_img_load()
    driver.substructure_query("Cl")
    hash_ = driver.get_svg_hash()
    assert (
        str(hash_) == "fdfffcfff8fffcfffdc7cdc780cf885bd901fb81f3b3f3bfff9fff1fff9fffbf"
    )


def test_callbacks_info(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"callback": mols2grid.callbacks.info()})
    driver.get(doc)
    driver.trigger_callback()
    modal = driver.find_by_css_selector("div.modal-content")
    assert (
        modal.find_element_by_css_selector(".modal-header .modal-title").get_attribute(
            "innerHTML"
        )
        == "CCC(C)CC"
    )
    content = modal.find_element_by_css_selector(
        ".modal-body .row .col:nth-child(2)"
    ).get_attribute("innerHTML")
    assert "PFEOZHBOMNWTJB-UHFFFAOYSA-N" in content


def test_callbacks_3D(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"callback": mols2grid.callbacks.show_3d()})
    driver.get(doc)
    driver.trigger_callback()
    modal = driver.find_by_css_selector("div.modal-content")
    assert (
        modal.find_element_by_css_selector(".modal-header .modal-title").get_attribute(
            "innerHTML"
        )
        == "CCC(C)CC"
    )
    content = modal.find_element_by_css_selector(".modal-body").get_attribute(
        "innerHTML"
    )
    assert '<div id="molviewer' in content
    # cannot test for actual rendering as there's no GL available
    assert driver.execute_script("return typeof($3Dmol)") != "undefined"


def test_callbacks_external_link(driver: FirefoxDriver, grid):
    doc = get_doc(grid, {"callback": mols2grid.callbacks.external_link()})
    driver.get(doc)
    driver.trigger_callback()
    # check if new tab was opened
    assert len(driver.window_handles) > 1
    urls = []
    for handle in driver.window_handles[1:]:
        driver.switch_to_window(handle)
        driver.wait(EC.url_contains("https://"))
        url = driver.current_url
        if url == "https://leruli.com/search/Q0NDKEMpQ0M=/home":
            break
        urls.append(url)
    else:
        raise AssertionError("Corresponding URL not found", urls)
