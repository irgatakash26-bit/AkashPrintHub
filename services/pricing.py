import os
import win32api
import win32print

BW_PRINTER = "Kyocera FS-1025MFP GX"
COLOR_PRINTER = "EPSON L3210 Series"

def list_printers():
    return [p[2] for p in win32print.EnumPrinters(2)]

def get_printer_for_service(service):
    if "color" in service.lower():
        return COLOR_PRINTER
    return BW_PRINTER

def print_file(file_path, service):
    printer_name = get_printer_for_service(service)

    if not os.path.exists(file_path):
        raise FileNotFoundError("File not found")

    win32print.SetDefaultPrinter(printer_name)
    win32api.ShellExecute(
        0,
        "print",
        file_path,
        None,
        ".",
        0
    )

    return printer_name 