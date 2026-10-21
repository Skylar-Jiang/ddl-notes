import tkinter as tk
from tkinter import ttk


LIGHT = dict(bg='#F4EFFA', header='#E5DAF0', text='#423B4C', muted='#81758D',
             accent='#78618F', line='#D9CDE4', field='#FFFCFF', danger='#AB5366')
DARK = dict(bg='#292630', header='#37313F', text='#EEE7F4', muted='#B4A7BF',
            accent='#C9AFDF', line='#51465C', field='#35303D', danger='#F0A5B4')
PASTELS = {
    'lavender': ('#EAE1F5', '#D4C4E6'), 'peach': ('#F7E5DF', '#E7CBC2'),
    'mint': ('#E2EFE7', '#C6DDD0'), 'blue': ('#E3EBF6', '#C8D7EA'),
    'butter': ('#F5EED8', '#E4D9B4')}
DARK_PASTELS = {
    'lavender': ('#3D354A', '#615071'), 'peach': ('#49383B', '#71545A'),
    'mint': ('#303F3B', '#4C665B'), 'blue': ('#303C4B', '#50647B'),
    'butter': ('#443F30', '#6F6347')}


def rounded(canvas, x1, y1, x2, y2, radius=14, **kwargs):
    radius = min(radius, (x2-x1)/2, (y2-y1)/2)
    return canvas.create_polygon(
        x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
        x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
        x1, y2, x1, y2-radius, x1, y1+radius, x1, y1,
        smooth=True, splinesteps=24, **kwargs)


class SoftButton(tk.Canvas):
    def __init__(self, parent, text, command, *, palette, width=32, height=30,
                 filled=False, icon=None, label=None, scale=1):
        self.p = palette
        self.command = command
        self.text = text
        self.icon = icon
        self.filled = filled
        self.hovered = False
        self.focused = False
        self.s = scale
        super().__init__(parent, width=round(width*scale), height=round(height*scale),
                         bg=parent.cget('bg'), highlightthickness=0, takefocus=1,
                         cursor='hand2', name=label)
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Enter>', lambda _: self.hover(True))
        self.bind('<Leave>', lambda _: self.hover(False))
        self.bind('<ButtonRelease-1>', self.click)
        self.bind('<Return>', lambda _: command())
        self.bind('<space>', lambda _: command())
        self.bind('<FocusIn>', lambda _: self.focus(True))
        self.bind('<FocusOut>', lambda _: self.focus(False))

    def click(self, event):
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def hover(self, value):
        self.hovered = value
        self.draw()

    def focus(self, value):
        self.focused = value
        self.draw()

    def draw(self):
        self.delete('all')
        w, h, s = self.winfo_width(), self.winfo_height(), self.s
        bg = self.p['header'] if self.filled or self.hovered else self.cget('bg')
        rounded(self, 1, 1, w-1, h-1, 10*s, fill=bg,
                outline=self.p['accent'] if self.focused else bg, width=1)
        if not self.icon:
            self.create_text(w/2, h/2, text=self.text, font=('Microsoft YaHei UI', 9), fill=self.p['text'])
            return
        cx, cy = w/2, h/2
        ink = self.p['text']
        def line(points, **kw):
            self.create_line(*[(cx+x*s if i%2 == 0 else cy+x*s) for i,x in enumerate(points)],
                             fill=ink, width=1.5*s, capstyle=tk.ROUND, **kw)
        if self.icon == 'close':
            line((-5,-5,5,5)); line((-5,5,5,-5))
        elif self.icon == 'minimize':
            line((-5,2,5,2))
        elif self.icon == 'collapse':
            line((-5,2,0,-3,5,2))
        elif self.icon == 'expand':
            line((-5,-2,0,3,5,-2))
        elif self.icon == 'pin':
            line((-3,-7,5,-3,2,0,2,4,-6,0,-3,-3,-3,-7)); line((-2,2,-6,8))
        elif self.icon == 'more':
            for x in (-6, 0, 6):
                self.create_oval(cx+(x-1)*s,cy-s,cx+(x+1)*s,cy+s,fill=ink,outline=ink)


class RoundedCard(tk.Canvas):
    def __init__(self, parent, fill, border, *, height, scale=1):
        super().__init__(parent, bg=parent.cget('bg'), height=height, highlightthickness=0)
        self.fill, self.border, self.s = fill, border, scale
        self.content = tk.Frame(self, bg=fill)
        self.item = self.create_window(12*scale, 9*scale, anchor='nw', window=self.content)
        self.bind('<Configure>', self.resize)

    def resize(self, event):
        self.delete('surface')
        rounded(self, 1, 1, event.width-1, event.height-1, 15*self.s, fill=self.fill,
                outline=self.border, width=1, tags='surface')
        self.tag_lower('surface')
        self.itemconfigure(self.item, width=max(1, event.width-24*self.s), height=event.height-18*self.s)


class RoundCheck(tk.Canvas):
    def __init__(self, parent, checked, command, palette, scale=1):
        self.checked, self.command, self.p, self.s = checked, command, palette, scale
        super().__init__(parent, width=round(23*scale), height=round(25*scale), bg=parent.cget('bg'),
                         highlightthickness=0, takefocus=1, cursor='hand2')
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<ButtonRelease-1>', lambda _: command())
        self.bind('<space>', lambda _: command())
        self.bind('<Return>', lambda _: command())
        self.bind('<FocusIn>', lambda _: self.draw(True))
        self.bind('<FocusOut>', lambda _: self.draw())

    def draw(self, focused=False):
        self.delete('all')
        s = self.s
        self.create_oval(2*s, 5*s, 17*s, 20*s, fill=self.p['accent'] if self.checked else self.cget('bg'),
                         outline=self.p['accent'] if focused or self.checked else self.p['muted'], width=1.2*s)
        if self.checked:
            self.create_line(5*s, 12*s, 8*s, 15*s, 14*s, 9*s, fill=self.p['bg'], width=1.7*s,
                             capstyle=tk.ROUND, joinstyle=tk.ROUND)


class ScrollArea(tk.Frame):
    def __init__(self, parent, palette):
        super().__init__(parent, bg=palette['bg'])
        self.canvas = tk.Canvas(self, bg=palette['bg'], highlightthickness=0)
        self.bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=palette['bg'])
        self.item = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.inner.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.bind('<Enter>', lambda _: self.canvas.bind_all('<MouseWheel>', self.wheel))
        self.bind('<Leave>', lambda _: self.canvas.unbind_all('<MouseWheel>'))

    def wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta/120), 'units')
