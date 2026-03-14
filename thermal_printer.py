"""
Thermal printer integration for ETOTC Church contribution management system.
Supports network thermal printers via ESC/POS protocol over TCP/IP (port 9100).
"""

import socket
import logging

logger = logging.getLogger(__name__)

PAPER_WIDTHS = {
    '80mm': 42,
    '58mm': 32,
}


def _build_member_lines(receipt_data, width):
    """Build compact list of (type, text) tuples for a member receipt."""
    sep  = '=' * width
    dash = '-' * width
    lines = []

    # ── Header (3 lines instead of 5) ────────────────────────────────────────
    lines += [
        ('center_bold', 'ETOTC Church'),
        ('center', '9256 227th Ave NE, Redmond WA 98053'),
        ('center', 'EIN: 91-1699080'),
        ('text', sep),
    ]

    # ── Receipt # and Date on one line ────────────────────────────────────────
    receipt_num = receipt_data.get('receipt_number', '')
    date_str    = receipt_data.get('date', '')
    lines.append(('text', _pad_line(f"#{receipt_num}", date_str, width)))

    # ── Member name and ID on one line ────────────────────────────────────────
    member_name = receipt_data.get('member_name', '')
    member_id   = receipt_data.get('member_id', '')
    lines.append(('text', _pad_line(member_name, member_id, width)))
    lines.append(('text', dash))

    # ── Payment lines ─────────────────────────────────────────────────────────
    for payment in receipt_data.get('payments', []):
        if payment.get('type') == 'donation':
            desc = f"Donation: {payment.get('reason', 'General')}"
        else:
            # Just the month name — "Contribution" is implied
            desc = payment.get('month', '')
        amount_str = f"${payment.get('amount', 0):.2f}"
        lines.append(('text', _pad_line(desc, amount_str, width)))

    lines.append(('text', dash))

    # ── Total ─────────────────────────────────────────────────────────────────
    total_str = f"${receipt_data.get('total', 0):.2f}"
    lines.append(('bold', _pad_line('TOTAL', total_str, width)))
    lines.append(('text', sep))

    # ── Payment method + processor on one line ────────────────────────────────
    method    = (receipt_data.get('payment_method') or 'Cash').replace('_', ' ').title()
    processor = receipt_data.get('processed_by') or 'N/A'
    lines.append(('text', _pad_line(method, f"By: {processor}", width)))

    # ── Footer (2 lines) ──────────────────────────────────────────────────────
    lines += [
        ('center', 'Thank you! God bless you.'),
        ('center', 'etotc.org'),
        ('feed', ''),
    ]
    return lines


def _build_non_member_lines(receipt_data, width):
    """Build compact list of (type, text) tuples for a non-member receipt."""
    sep  = '=' * width
    dash = '-' * width
    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        ('center_bold', 'ETOTC Church'),
        ('center', '9256 227th Ave NE, Redmond WA 98053'),
        ('center', 'EIN: 91-1699080'),
        ('text', sep),
    ]

    # ── Receipt # and Date on one line ────────────────────────────────────────
    receipt_num = receipt_data.get('receipt_number', '')
    date_str    = receipt_data.get('date', '')
    lines.append(('text', _pad_line(f"#{receipt_num}", date_str, width)))

    # ── Guest info ────────────────────────────────────────────────────────────
    name = receipt_data.get('name', 'Guest')
    lines.append(('text', name))
    # Email and phone on one line if both present, else each on own line
    email = receipt_data.get('email', '')
    phone = receipt_data.get('phone', '')
    if email and phone:
        lines.append(('text', _pad_line(email, phone, width)))
    elif email:
        lines.append(('text', email))
    elif phone:
        lines.append(('text', phone))
    lines.append(('text', dash))

    # ── Line items ────────────────────────────────────────────────────────────
    for item in receipt_data.get('line_items', []):
        desc       = item.get('description', 'General')
        amount_str = f"${item.get('amount', 0):.2f}"
        lines.append(('text', _pad_line(desc, amount_str, width)))

    lines.append(('text', dash))

    # ── Total ─────────────────────────────────────────────────────────────────
    total_str = f"${receipt_data.get('total', 0):.2f}"
    lines.append(('bold', _pad_line('TOTAL', total_str, width)))
    lines.append(('text', sep))

    # ── Payment method + processor on one line ────────────────────────────────
    method    = (receipt_data.get('payment_method') or 'Cash').replace('_', ' ').title()
    processor = receipt_data.get('processed_by') or 'N/A'
    lines.append(('text', _pad_line(method, f"By: {processor}", width)))

    if receipt_data.get('payment_comment'):
        comment = receipt_data['payment_comment']
        # Wrap long comments at word boundaries
        for chunk in _wrap(comment, width):
            lines.append(('text', chunk))

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        ('center', 'Thank you! God bless you.'),
        ('center', 'etotc.org'),
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


def _wrap(text, width):
    """Simple word-wrap returning list of lines no longer than `width`."""
    words, lines, current = text.split(), [], ''
    for word in words:
        if len(current) + len(word) + (1 if current else 0) <= width:
            current = (current + ' ' + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


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
            if line_type == 'center_bold':
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
    ESC    = b'\x1b'
    INIT   = ESC + b'@'
    ALIGN_L = ESC + b'a\x00'
    ALIGN_C = ESC + b'a\x01'
    BOLD_ON  = ESC + b'E\x01'
    BOLD_OFF = ESC + b'E\x00'
    FEED3   = b'\n\n\n'

    buf = bytearray()
    buf += INIT

    for line_type, text in lines:
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

    buf += b'\x1d\x56\x00'  # Full cut

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
        ('center_bold', 'ETOTC Church'),
        ('center', 'Printer Test Page'),
        ('text', sep),
        ('text', _pad_line('IP:', printer_ip, width)),
        ('text', _pad_line('Port:', str(printer_port), width)),
        ('text', _pad_line('Status:', 'CONNECTED', width)),
        ('text', sep),
        ('center', 'Printer is ready.'),
        ('feed', ''),
    ]
    return _send_lines(test_lines, printer_ip, printer_port, timeout)
