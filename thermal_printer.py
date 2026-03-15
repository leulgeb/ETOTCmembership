"""
Thermal printer integration for ETOTC Church contribution management system.
Supports network thermal printers via ESC/POS protocol over TCP/IP (port 9100).
"""

import os
import socket
import logging

logger = logging.getLogger(__name__)

PAPER_WIDTHS = {
    '80mm': 42,
    '58mm': 32,
}

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'static', 'images', 'etotc_logo.png')


def _wrap_payment_line(desc, amount_str, width):
    """
    Return a list of ('text', line) tuples for a single payment entry.
    The description wraps to additional lines instead of being truncated.
    The amount is right-aligned on the last line alongside the description.
    """
    amount_col = len(amount_str)
    max_desc_with_amount = width - amount_col - 1

    if len(desc) <= max_desc_with_amount:
        gap = width - len(desc) - amount_col
        return [('text', desc + (' ' * max(gap, 1)) + amount_str)]

    words = desc.split()
    lines_out = []
    current = ''

    for word in words:
        test = (current + ' ' + word).strip()
        if len(test) <= width:
            current = test
        else:
            if current:
                lines_out.append(current)
            current = word

    if current:
        if len(current) <= max_desc_with_amount:
            gap = width - len(current) - amount_col
            lines_out.append(current + (' ' * max(gap, 1)) + amount_str)
        else:
            lines_out.append(current)
            lines_out.append(' ' * (width - amount_col) + amount_str)
    elif lines_out:
        lines_out.append(' ' * (width - amount_col) + amount_str)

    return [('text', l) for l in lines_out]


def _build_member_lines(receipt_data, width):
    """Build list of (type, text) tuples for a member receipt."""
    sep = '=' * width
    dash = '-' * width
    lines = []

    lines.append(('logo', LOGO_PATH))

    lines += [
        ('center_bold', 'ETOTC Church'),
        ('center', '2101 14th Ave S'),
        ('center', 'Seattle, WA 98144'),
        ('center', 'EIN: 91-1699080'),
        ('text', sep),
        ('text', f"Receipt#: {receipt_data.get('receipt_number', '')}"),
        ('text', f"Date:     {receipt_data.get('date', '')}"),
        ('text', sep),
        ('text', f"Member: {receipt_data.get('member_name', '')}"),
        ('text', f"ID:     {receipt_data.get('member_id', '')}"),
        ('text', sep),
    ]

    all_payments = receipt_data.get('payments', [])
    contribs = [p for p in all_payments if p.get('type') != 'donation']
    donations = [p for p in all_payments if p.get('type') == 'donation']

    by_year = {}
    for p in contribs:
        yr = p.get('year', '')
        if yr not in by_year:
            by_year[yr] = []
        by_year[yr].append(p)

    for yr in sorted(by_year.keys()):
        yr_payments = by_year[yr]
        yr_total = sum(p.get('amount', 0) for p in yr_payments)
        if len(yr_payments) == 1:
            desc = f"{yr_payments[0].get('month', '')} {yr} Contribution"
        else:
            desc = f"{yr_payments[0].get('month', '')} to {yr_payments[-1].get('month', '')} {yr} Contribution"
        amount_str = f"${yr_total:.2f}"
        lines.extend(_wrap_payment_line(desc, amount_str, width))

    for payment in donations:
        reason = payment.get('reason', 'General')
        desc = f"Donation: {reason}" if reason else "Donation"
        amount_str = f"${payment.get('amount', 0):.2f}"
        lines.extend(_wrap_payment_line(desc, amount_str, width))

    total_str = f"${receipt_data.get('total', 0):.2f}"
    lines.append(('bold', _pad_line('TOTAL:', total_str, width)))
    lines.append(('text', sep))

    method = (receipt_data.get('payment_method') or 'Cash').title()
    processor = receipt_data.get('processed_by') or 'N/A'
    lines += [
        ('text', f"Payment:     {method}"),
        ('text', f"Received By: {processor}"),
        ('text', sep),
    ]

    lines += [
        ('center', 'Thank you for your contribution!'),
        ('center', 'God bless you.'),
        ('center', 'ETOTC.org'),
        ('feed', ''),
    ]
    return lines


def _build_non_member_lines(receipt_data, width):
    """Build list of (type, text) tuples for a non-member receipt."""
    sep = '=' * width
    dash = '-' * width
    lines = []

    lines.append(('logo', LOGO_PATH))

    lines += [
        ('center_bold', 'ETOTC Church'),
        ('center', '2101 14th Ave S'),
        ('center', 'Seattle, WA 98144'),
        ('center', 'EIN: 91-1699080'),
        ('text', sep),
        ('text', f"Receipt#: {receipt_data.get('receipt_number', '')}"),
        ('text', f"Date:     {receipt_data.get('date', '')}"),
        ('text', sep),
        ('text', f"Guest: {receipt_data.get('name', '')}"),
    ]
    if receipt_data.get('email'):
        lines.append(('text', f"Email: {receipt_data['email']}"))
    if receipt_data.get('phone'):
        lines.append(('text', f"Phone: {receipt_data['phone']}"))
    lines.append(('text', sep))

    for item in receipt_data.get('line_items', []):
        desc = item.get('description', 'General')
        amount_str = f"${item.get('amount', 0):.2f}"
        lines.extend(_wrap_payment_line(desc, amount_str, width))

    total_str = f"${receipt_data.get('total', 0):.2f}"
    lines.append(('bold', _pad_line('TOTAL:', total_str, width)))
    lines.append(('text', sep))

    method = (receipt_data.get('payment_method') or 'Cash').replace('_', ' ').title()
    processor = receipt_data.get('processed_by') or 'N/A'
    lines += [
        ('text', f"Payment:     {method}"),
        ('text', f"Received By: {processor}"),
    ]
    if receipt_data.get('payment_comment'):
        lines.append(('text', f"Note: {receipt_data['payment_comment']}"))
    lines += [
        ('text', sep),
        ('center', 'Thank you for your contribution!'),
        ('center', 'God bless you.'),
        ('center', 'ETOTC.org'),
        ('feed', ''),
    ]
    return lines


def _pad_line(left, right, width):
    """Left-align `left` and right-align `right` within `width` characters."""
    max_left = width - len(right) - 1
    if len(left) > max_left:
        left = left[:max_left - 2] + '..'
    gap = width - len(left) - len(right)
    return left + (' ' * max(gap, 1)) + right


def _send_lines(lines, printer_ip, printer_port, timeout):
    """
    Send formatted lines to a network thermal printer using raw ESC/POS bytes.
    Uses python-escpos library if available, otherwise falls back to raw socket.
    """
    try:
        from escpos.printer import Network
        p = Network(host=printer_ip, port=int(printer_port), timeout=timeout)
        p.hw('INIT')

        for line_type, text in lines:
            if line_type == 'logo':
                if os.path.exists(text):
                    try:
                        p.set(align='center')
                        p.image(text)
                        p.set(align='left')
                    except Exception as e:
                        logger.warning(f"Logo print skipped: {e}")
            elif line_type == 'center_bold':
                p.set(align='center', bold=True, text_type='B')
                p.text(text + '\n')
                p.set(align='left', bold=False, text_type='NORMAL')
            elif line_type == 'center':
                p.set(align='center')
                p.text(text + '\n')
                p.set(align='left')
            elif line_type == 'bold':
                p.set(bold=True)
                p.text(text + '\n')
                p.set(bold=False)
            elif line_type == 'feed':
                p.text('\n\n\n')
            else:
                p.text(text + '\n')

        p.cut()
        p.close()
        return True, "Receipt printed successfully!"

    except ImportError:
        return _send_raw(lines, printer_ip, printer_port, timeout)

    except Exception as e:
        logger.error(f"ESC/POS printer error: {e}")
        return False, f"Printer error: {str(e)}"


def _send_raw(lines, printer_ip, printer_port, timeout):
    """Fallback: send ESC/POS as raw bytes over a socket."""
    ESC = b'\x1b'
    INIT    = ESC + b'@'
    ALIGN_L = ESC + b'a\x00'
    ALIGN_C = ESC + b'a\x01'
    BOLD_ON  = ESC + b'E\x01'
    BOLD_OFF = ESC + b'E\x00'
    CUT      = ESC + b'i'
    FEED3    = b'\n\n\n'

    buf = bytearray()
    buf += INIT

    for line_type, text in lines:
        if line_type == 'logo':
            continue
        encoded = (text + '\n').encode('ascii', errors='replace')
        if line_type == 'center_bold':
            buf += ALIGN_C + BOLD_ON + encoded + BOLD_OFF + ALIGN_L
        elif line_type == 'center':
            buf += ALIGN_C + encoded + ALIGN_L
        elif line_type == 'bold':
            buf += BOLD_ON + encoded + BOLD_OFF
        elif line_type == 'feed':
            buf += FEED3
        else:
            buf += encoded

    buf += CUT

    try:
        with socket.create_connection((printer_ip, int(printer_port)), timeout=timeout) as sock:
            sock.sendall(bytes(buf))
        return True, "Receipt printed successfully! (raw mode)"
    except Exception as e:
        logger.error(f"Raw socket printer error: {e}")
        return False, f"Socket error: {str(e)}"


def _check_connection(printer_ip, printer_port, timeout):
    """Quick TCP check before attempting to print."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((printer_ip, int(printer_port)))
        sock.close()
        return result == 0
    except Exception:
        return False


def print_member_receipt(receipt_data, printer_ip, printer_port=9100,
                         paper_width='80mm', timeout=5):
    """
    Print a member contribution receipt on a network thermal printer.

    Returns: (success: bool, message: str)
    """
    if not _check_connection(printer_ip, printer_port, timeout):
        return False, (
            f"Cannot reach printer at {printer_ip}:{printer_port}. "
            "Check that the printer is powered on and connected to the network."
        )
    width = PAPER_WIDTHS.get(paper_width, 42)
    lines = _build_member_lines(receipt_data, width)
    return _send_lines(lines, printer_ip, printer_port, timeout)


def print_non_member_receipt(receipt_data, printer_ip, printer_port=9100,
                             paper_width='80mm', timeout=5):
    """
    Print a non-member/guest receipt on a network thermal printer.

    Returns: (success: bool, message: str)
    """
    if not _check_connection(printer_ip, printer_port, timeout):
        return False, (
            f"Cannot reach printer at {printer_ip}:{printer_port}. "
            "Check that the printer is powered on and connected to the network."
        )
    width = PAPER_WIDTHS.get(paper_width, 42)
    lines = _build_non_member_lines(receipt_data, width)
    return _send_lines(lines, printer_ip, printer_port, timeout)


def test_printer_connection(printer_ip, printer_port=9100, timeout=5):
    """
    Test connection and print a test page.

    Returns: (success: bool, message: str)
    """
    if not _check_connection(printer_ip, printer_port, timeout):
        return False, (
            f"Cannot reach printer at {printer_ip}:{printer_port}. "
            "Verify the IP address, port, and that the printer is online."
        )

    width = 42
    sep = '=' * width
    test_lines = [
        ('logo', LOGO_PATH),
        ('center_bold', 'ETOTC Church'),
        ('center', 'Printer Test Page'),
        ('text', sep),
        ('text', f"IP Address: {printer_ip}"),
        ('text', f"Port:       {printer_port}"),
        ('text', f"Status:     CONNECTED"),
        ('text', sep),
        ('center', 'Test successful! Printer is ready.'),
        ('feed', ''),
    ]
    return _send_lines(test_lines, printer_ip, printer_port, timeout)
