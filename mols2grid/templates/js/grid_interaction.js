// Check if selection UI is supported.
var supportSelection = eval('{{selection}}'.toLowerCase());

listObj.on("updated", initInteraction);

// (Re)initialiuze all grid interaction every time the grid changes.
function initInteraction(list) {
    initCellClick()
    initToolTip()
    initKeyboard()
    if (supportSelection) initCheckbox()

    // Hide navigation if there is only one page.
    if (listObj.matchingItems.length <= listObj.page) {
        $('#mols2grid .m2g-pagination').hide()
    } else {
        $('#mols2grid .m2g-pagination').show()
    }

    // Add a bunch of phantom cells.
    // These are used as filler to make sure that
    // no grid cells need to be resized when there's
    // not enough results to fill the row.
    $('#mols2grid .m2g-list').append('<div class="m2g-cell m2g-phantom"></div>'.repeat(11));
}

// Cell click handler.
function initCellClick() {
    $('#mols2grid .m2g-cell').off('click').click(function(e) {
        if ($(e.target).hasClass('m2g-info')) {
            var isVisible = $('div.popover[role=tooltip]').length
        } else if ($(e.target).is('div') && $(e.target).hasClass('data')) {
            // Copy text when clicking a data string.
            var text = $(e.target).text()
            navigator.clipboard.writeText(text)

            // Blink the cell to indicate that the text was copied.
            $(e.target).addClass('m2g-copy-blink')
            setTimeout(function() {
                $(e.target).removeClass('m2g-copy-blink')
            }, 450)
        } else if (!$(e.target).is(':checkbox')) {
            if (supportSelection) {
                // When clicking anywhere outside the checkbox, toggle the checkbox.
                var chkbox = $(this).find('input:checkbox')[0]
                chkbox.checked = !chkbox.checked
                $(chkbox).trigger('change')
            }
        }
    })
}

// Keyboard actions.
function initKeyboard() {
    // Disable scroll when pressing UP/DOWN arrows
    $('#mols2grid .m2g-cell').off('keydown').keydown(function(e) {
        if (e.which == 38 || e.which == 40) {
            e.preventDefault()
        }
    })

    $('#mols2grid .m2g-cell').off('keyup').keyup(function(e) {
        // console.log(e.which)
        var chkbox = $(this).find('input:checkbox')[0]
        if (e.which == 13) {
            // ENTER: toggle
            chkbox.checked = !chkbox.checked
            $(chkbox).trigger('change')
        } else if (e.which == 27 || e.which == 8) {
            // ESC/BACKSPACE: unselect
            chkbox.checked = false
            $(chkbox).trigger('change')
        } else if (e.which == 37) {
            // LEFT
            $(this).prev().focus()
        } else if (e.which == 39) {
            // RIGHT
            $(this).next().focus()
        } else if (e.which == 38 || e.which == 40) {
            var containerWidth = $(this).parent().outerWidth()
            var cellWidth = $(this).outerWidth() + parseInt($(this).css('marginLeft')) * 2
            var columns = Math.round(containerWidth / cellWidth)
            var index = $(this).index()
            if (e.which == 38) {
                // UP
                var indexAbove = Math.max(index - columns, 0)
                $(this).parent().children().eq(indexAbove).focus()
            } else if (e.which == 40) {
                // DOWN    
                var total = $(this).parent().children().length
                var indexBelow = Math.min(index + columns, total)
                $(this).parent().children().eq(indexBelow).focus()
            }
        }
    })
}

// Show tooltip when hovering the info icon.
function initToolTip() {
    $('#mols2grid .m2g-info').off('mouseover').off('mouseleave').off('click').mouseenter(function() {
        // Show on enter
        $(this).parent().find('.mols2grid-tooltip[data-toggle="popover"]').popover('show')
    }).mouseleave(function() {
        // Hide on leave, unless sticky.
        if (!$(this).parent().hasClass('m2g-keep-tooltip')) {
            $(this).parent().find('.mols2grid-tooltip[data-toggle="popover"]').popover('hide')
        }
    }).click(function() {
        // Toggle sticky on click.
        $(this).parent().toggleClass('m2g-keep-tooltip')

        // Hide tooltip when sticky was turned off.
        if ($(this).parent().hasClass('m2g-keep-tooltip')) {
            $(this).parent().find('.mols2grid-tooltip[data-toggle="popover"]').popover('show')
        } else if (!$(this).parent().hasClass('m2g-keep-tooltip')) {
            $(this).parent().find('.mols2grid-tooltip[data-toggle="popover"]').popover('hide')
        }
    })
}

// Update selection on checkbox click.
function initCheckbox() {
    $("input:checkbox").off('change').change(function() {
        var _id = parseInt($(this).closest(".m2g-cell").attr("data-mols2grid-id"));
        if (this.checked) {
            var _smiles = $($(this).closest(".m2g-cell").children(".data-{{ smiles_col }}")[0]).text();
            add_selection({{ grid_id | tojson }}, [_id], [_smiles]);
        } else {
            del_selection({{ grid_id | tojson }}, [_id]);
        }
    });
}



/**
 * Actions
 */

// Listen to action dropdown.
$('#mols2grid .m2g-actions select').change(function(e) {
    var val = e.target.value
    switch(val) {
        case 'select-all':
            selectAll()
            break
        case 'select-matching':
            selectMatching()
            break
        case 'unselect-all':
            unselectAll()
            break
        case 'invert':
            invertSelection()
            break
        case 'copy':
            copy()
            break
        case 'save-smiles':
            saveSmiles()
            break
        case 'save-csv':
            saveCSV()
            break
    }
    $(this).val('') // Reset dropdown
})

// Check all.
function selectAll(e) {
    var _id = [];
    var _smiles = [];
    listObj.items.forEach(function (item) {
        if (item.elm) {
            item.elm.getElementsByTagName("input")[0].checked = true;
        } else {
            item.show()
            item.elm.getElementsByTagName("input")[0].checked = true;
            item.hide()
        }
        _id.push(item.values()["mols2grid-id"]);
        _smiles.push(item.values()["data-{{ smiles_col }}"]);
    });
    add_selection({{ grid_id | tojson }}, _id, _smiles);
};


// Check matching.
function selectMatching(e) {
    var _id = [];
    var _smiles = [];
    listObj.matchingItems.forEach(function (item) {
        if (item.elm) {
            item.elm.getElementsByTagName("input")[0].checked = true;
        } else {
            item.show()
            item.elm.getElementsByTagName("input")[0].checked = true;
            item.hide()
        }
        _id.push(item.values()["mols2grid-id"]);
        _smiles.push(item.values()["data-{{ smiles_col }}"]);
    });
    add_selection({{ grid_id | tojson }}, _id, _smiles);
};

// Uncheck all.
function unselectAll(e) {
    var _id = [];
    listObj.items.forEach(function (item) {
        if (item.elm) {
            item.elm.getElementsByTagName("input")[0].checked = false;
        } else {
            item.show()
            item.elm.getElementsByTagName("input")[0].checked = false;
            item.hide()
        }
        _id.push(item.values()["mols2grid-id"]);
    });
    del_selection({{ grid_id | tojson }}, _id);
};

// Invert selection.
function invertSelection(e) {
    var _id_add = [];
    var _id_del = [];
    var _smiles = [];
    listObj.items.forEach(function (item) {
        if (item.elm) {
            var chkbox = item.elm.getElementsByTagName("input")[0]
            chkbox.checked = !chkbox.checked;
        } else {
            item.show()
            var chkbox = item.elm.getElementsByTagName("input")[0]
            chkbox.checked = !chkbox.checked;
            item.hide()
        }
        if (chkbox.checked) {
            _id_add.push(item.values()["mols2grid-id"]);
            _smiles.push(item.values()["data-{{ smiles_col }}"]);
        } else {
            _id_del.push(item.values()["mols2grid-id"]);
        }
    });
    del_selection({{ grid_id | tojson }}, _id_del);
    add_selection({{ grid_id | tojson }}, _id_add, _smiles);
};

// Copy to clipboard.
function copy(e) {
    navigator.clipboard.writeText(SELECTION.to_dict());
};

// Export smiles.
function saveSmiles(e) {
    var fileName = "selection.smi"
    if (SELECTION.size) {
        // Download selected smiles
        SELECTION.download_smi(fileName);
    } else {
        // Download all smiles
        SELECTION.download_smi(fileName, listObj.items);
    }
};

// Export CSV.
function saveCSV(e) {
    console.log(SELECTION)
    return
    var sep = "\t"
    // Same order as subset + tooltip
    var columns = Array.from(listObj.items[0].elm.querySelectorAll("div.data"))
                       .map(elm => elm.classList[1])
                       .filter(name => name !== "data-img");
    // Remove 'data-' and img
    var header = columns.map(name => name.slice(5));
    // CSV content
    header = ["index"].concat(header).join(sep);
    var content = header + "\n";
    listObj.items.forEach(function (item) {
        let data = item.values();
        let index = data["mols2grid-id"];
        if (SELECTION.has(index) || SELECTION.size === 0) {
            content += index;
            columns.forEach((key) => {
                content += sep + data[key];
            })
            content += "\n";
        }
    });
    var a = document.createElement("a");
    var file = new Blob([content], {type: "text/csv"});
    a.href = URL.createObjectURL(file);
    a.download = "selection.csv";
    a.click();
    a.remove();
};