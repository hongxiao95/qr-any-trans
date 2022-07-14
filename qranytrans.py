#coding:utf-8


from threading import Thread
from tkinter import *
from tkinter.ttk import *
from tkinter.filedialog import askopenfilename
from tkinter import messagebox
import os
from io import BytesIO
from PIL import Image, ImageTk
import time
import math
import qrcode


from numpy import byte

from transfer.TransferV1 import CODE_PROT_SINGLE_CLR, DATA_PROT_BYTES, DATA_PROT_V_1, TransferV1


app_version = "1.0 Beta"
# 最大50M
MAX_FILE_SIZE = 1024 * 1024 * 50
CANVAS_SIDE_SIZE = 450
CANVAS_SIDE_PADDING_RATE = 1
CANVAS_COL = 3

IMAGE_BUFFER_SIZE = 6

# 使用的码版本
USING_VERSION = 22
# 使用的编码方式，默认b85
USING_ENCODE = "base85"
# 使用的异或校验频率， 默认无。可选范围：[1~128], 低于1无，1为和全1异或。高于1000为1000
USING_CHECK_FRQ = 0


AUTHOR_DESC = f"版本: {app_version}  ©HONG Xiao hongxiao95@hotmail.com"

# 计算bytes列表异或
def bytes_list_xor(bytes_li):
    if len(bytes_li) < 2:
        raise Exception("异或list长度不足2")

    for i in range(1, len(bytes_li)):
        if len(bytes_li[i]) - len(bytes_li[i - 1]) != 0:
            raise Exception(f"异或列表元素长度不一致，第{i}项为{len(bytes_li[i])}, 第{i - 1}项为{len(bytes_li[i - 1])}")
    
    res = bytearray(bytes_li[0])

    for i in range(1, len(bytes_li)):
        for j in range(len(res)):
            res[j] ^= bytes_li[i][j]

    res = bytes(res)

    return res

# 和全1异或
def xor_with_one(in_bytes:bytes) -> bytes:
    br = bytearray(in_bytes)
    for i in range(len(br)):
        br[i] = br[i] ^ 0xff

    return bytes(br)

class QrAnyTransUI():
    def __init__(self):
        self.main_win = Tk()
        self.main_win.wm_title("任意传输器")
        self.pure_file_name = ""
        self.img_tk_buffer = [0 for i in range(IMAGE_BUFFER_SIZE)]
        self.img_handles = [0 for i in range(IMAGE_BUFFER_SIZE)]
        self.buffer_index = 0

        self.source_file = None
        self.source_bio = BytesIO()
        self.transfer = None

        self.is_pause = False
        self.call_stop = False
        self.is_stoped = False
        self.rec_thread = None
        self.check_frame_count = 0

        self._prepare_components()
        self.reset_app()        

    def run(self):
        self.main_win.mainloop()

    def _prepare_components(self):
        # 选择文件按钮
        self.chosen_file_name_var = StringVar()
        self.choose_file_entry = Entry(self.main_win, state="readonly", textvariable=self.chosen_file_name_var)
        self.choose_file_btn = Button(self.main_win, text = "请选择文件", command=self.ask_file)
        self.choose_file_entry.grid(column=0, row=0, columnspan=6, sticky=EW)
        self.choose_file_btn.grid(column=6, row=0, columnspan=2, sticky=EW)

        # 二维码展示区域
        self.qr_canvas = Canvas(self.main_win, width=int(CANVAS_SIDE_SIZE * CANVAS_SIDE_PADDING_RATE * CANVAS_COL), height=CANVAS_SIDE_SIZE, background="white")
        self.qr_canvas.grid(column=0, row=1, columnspan=8, rowspan=8)

        # 二维码播放区域
        # 速度调节 
        self.speed_var = DoubleVar()
        self.speed_var.set(5)

        self.speed_var_int = IntVar()
        self.speed_var_int.set(5)

        self.speed_label = Label(self.main_win, text="速率调节")
        self.speed_scale = Scale(self.main_win, from_=1, to=15, variable=self.speed_var, \
            command=lambda x: self.speed_var_int.set(int(float(x))))
        self.speed_value_label = Label(self.main_win, textvariable=self.speed_var_int)

        self.speed_label.grid(column=0, row=9, sticky=EW)
        self.speed_scale.grid(column=1, row=9, columnspan=6, sticky=EW)
        self.speed_value_label.grid(column=7, row=9, sticky=E)

        # 开始/继续 暂停 停止（归零）
        self.start_btn_var = StringVar()
        self.start_btn_var.set("开始")
        self.start_btn = Button(self.main_win, textvariable=self.start_btn_var, command=self.on_start_btn)
        self.pause_btn = Button(self.main_win, text="暂停", command=self.on_pause_btn)
        self.stop_btn = Button(self.main_win, text="停止", command=self.on_stop_btn)
        self.start_btn.grid(column=0, row=10, columnspan=4, sticky=EW)
        self.pause_btn.grid(column=4, row=10, columnspan=2, sticky=EW)
        self.stop_btn.grid(column=6, row=10, columnspan=2, sticky=EW)

        # 补帧
        self.patch_frame_checkbtn_var = BooleanVar()
        self.patch_frame_checkbtn_var.set(False)
        self.patch_frame_checkbtn = Checkbutton(self.main_win, onvalue=True, offvalue=False, text="补帧", variable=self.patch_frame_checkbtn_var)
        
        self.patch_frames_var = StringVar()
        self.patch_frames_var.set("")
        self.patch_entry = Entry(self.main_win, textvariable=self.patch_frames_var)

        self.patch_frame_checkbtn.grid(column=0, row=11, sticky=EW)
        self.patch_entry.grid(column=1, row=11, columnspan=7, sticky=EW)

        # 上一帧 下一帧
        self.prev_frame_btn = Button(self.main_win, text="上一帧")
        self.next_frame_btn = Button(self.main_win, text="下一帧")

        self.prev_frame_btn.grid(column=0, row=12, columnspan=1, sticky=EW)
        self.next_frame_btn.grid(column=1, row=12, columnspan=3, sticky=EW)

        # 跳转到某帧
        self.skip_spin_box = Spinbox(self.main_win, from_=0, to=1000, value=0, increment=1, validate="focus", validatecommand=self._check_skip_frame_spinbox, width=10)
        self.skip_prev_lable = Label(self.main_win, text="跳到")
        self.skip_after_label = Label(self.main_win, text="帧")
        self.skip_go_btn = Button(self.main_win, text="Go")

        self.skip_prev_lable.grid(column=4, row=12, sticky=EW)
        self.skip_spin_box.grid(column=5, row=12)
        self.skip_after_label.grid(column=6, row=12, sticky=EW)
        self.skip_go_btn.grid(column=7, row=12, sticky=EW)

        # 执行信息
        self.file_size_var = StringVar()
        self._set_file_size_tip(is_reset=True)
        self.file_size_label = Label(self.main_win, textvariable=self.file_size_var)

        self.file_speed_var = StringVar()
        self._set_file_speed_tip(is_reset=True)
        self.file_speed_label = Label(self.main_win, textvariable=self.file_speed_var)

        self.cur_tips = StringVar()
        self.reset_tip()
        self.cur_frame_label = Label(self.main_win, textvariable=self.cur_tips)

        self.file_size_label.grid(column=0, row=13, columnspan=2, sticky=W)
        self.file_speed_label.grid(column=2, row=13, columnspan=3, sticky=W)
        self.cur_frame_label.grid(column=5, row=13, columnspan=3, sticky=E)


        # 进度条
        self.progress_var = IntVar()
        self.progress_var.set(0)
        self.progress_bar = Progressbar(self.main_win, maximum=100, variable=self.progress_var, mode="determinate")
        self.progress_bar.grid(column=0, row=14, columnspan=8, sticky=EW)

        # 接收
        self.receive_btn = Button(self.main_win, text="收", command=self.on_rec_btn)
        self.receive_btn.grid(column=0, row=15, sticky=W)

        # 作者信息
        self.author_info_label = Label(self.main_win, text=AUTHOR_DESC, foreground="gray")
        self.author_info_label.grid(column=0, row=15, columnspan=8, sticky=E)


        return

    def on_rec_btn(self):
        if (self.rec_thread is None) or (self.rec_thread.is_alive() == False):
            self.rec_thread = Thread(target=lambda: QrReceiverUI(self.main_win).run(), name="QrReceiver-Thread", daemon=True)
            self.rec_thread.start()

    def reset_app(self):
        '''
        重置整个应用，清除当前选择的文件和缓存
        '''
        self.source_file = None
        self.source_bio = BytesIO()
        self.transfer = None
        self.pure_file_name = ""
        self.reset_tip()
        self.reset_task()

    def reset_task(self):
        
        # 重置传输器
        if (self.transfer is None) == False:
            self.transfer.reset_transfer_state()
            self.update_tip(f"文件初始化完成, Meta帧 / {self.transfer.total_batch_count} / {self.check_frame_count}帧")


        # 重置二维码区域
        self.qr_canvas.delete("all")

        # 重置速率
        self.speed_var.set(5)
        self.speed_var_int.set(5)

        # 重置校验帧数
        self.check_frame_count = 0

        # 重置跳转帧数
        self.skip_spin_box.set(0)

        # 重置各按钮状态
        self.start_btn_var.set("开始")
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.prev_frame_btn.config(state="disabled")
        self.next_frame_btn.config(state="disabled")
        self.skip_go_btn.config(state="disabled")

        # 重置进度条
        self.progress_var.set(0)

        self.qr_canvas.delete("all")
        self.img_tk_buffer = [0 for i in range(IMAGE_BUFFER_SIZE)]
        self.img_handles = [0 for i in range(IMAGE_BUFFER_SIZE)]
        self.buffer_index = 0

        # 重置传输速度
        self._set_file_speed_tip(is_reset=True)

        # 重置暂停和停止标识符
        self.is_pause = False
        self.call_stop = False
        self.is_stoped = False

        return

    def _set_file_speed_tip(self, file_speed_KB:float = 0, fps:float=0, est_s:float=0, is_reset:bool = False):
        if is_reset:
            self.file_speed_var.set("当前无速度")
            return

        self.file_speed_var.set(f"均速:{file_speed_KB:5.2f}KB/s, fps:{fps:5.2f}, est: {est_s:5.0f} s")

    def _set_file_size_tip(self, file_size_B:int = 0, is_reset = False):
        if is_reset:
            self.file_size_var.set("未选择文件")
            return

        unit = "B"
        file_size = file_size_B
        if file_size > 1024:
            file_size = file_size / 1024
            unit = "KB"
            if file_size > 1024:
                file_size = file_size / 1024
                unit = "MB"
        self.file_size_var.set(f"大小：{file_size:.2f} {unit}")
        return   

    def on_start_btn(self):
        if self.transfer is None:
            messagebox.showerror("无法开始","未选择文件!")
            return

        # 暂停和停止时按钮功能变化
        if self.is_pause is False:
            self.call_stop = False
            self.is_stoped = False
            
            self.transfer_thread = Thread(target=self.run_task, name="run_task_thread", daemon=True)
            self.transfer_thread.start()
            
        else:
            # 暂停时的处理
            self.is_stoped = False
            self.is_pause = False
        
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.stop_btn.config(state="normal")

    def on_pause_btn(self):
        self.is_pause = True
        self.pause_btn.config(state="disabled")
        self.start_btn.config(state="normal")
        self.start_btn_var.set("继续")

    def on_stop_btn(self):
        self.call_stop = True
        self.is_pause = False
        # 扔到另外的线程做停止完成的后续工作
        wait_stop_thread = Thread(target=self._wait_for_stop_success, name="wait_stop_thread", daemon=True)
        wait_stop_thread.start()
        

    def _wait_for_stop_success(self):
        while True:
            if self.is_stoped is True:
                break
            time.sleep(0.2)
            
        self.pause_btn.config(state="disabled")
        self.start_btn.config(state="normal")
        self.start_btn_var.set("开始")
        self.reset_task()

    def update_tip(self, tip):
        self.cur_tips.set(f"{tip}, 码版本[{USING_VERSION}]，编码[{USING_ENCODE}]，校验间隔[{USING_CHECK_FRQ}]")

    def reset_tip(self):
        self.cur_tips.set(f"当前无任务,码版本[{USING_VERSION}]，编码[{USING_ENCODE}]，校验间隔[{USING_CHECK_FRQ}]")
        self._set_file_speed_tip(is_reset=True)
        self._set_file_size_tip(is_reset=True)

    def ask_file(self):

        # 先重置所有状态
        self.reset_app()

        # 获取文件名
        file_name = askopenfilename()
        file_name = file_name.replace("/", os.sep)
        
        # 判断文件大小
        with open(file_name, "rb") as tryfile:
            tryfile.seek(0, 2)
            file_size_b = tryfile.tell()
            if file_size_b > MAX_FILE_SIZE:
                messagebox.showerror("文件过大！",f"文件最大限制为{MAX_FILE_SIZE/1024/1024:.2f}MB， 过大文件可考虑分卷压缩")
                return
            self._set_file_size_tip(file_size_b)
            self.pure_file_name = file_name.split(os.sep)[-1]
            self.chosen_file_name_var.set(file_name)
            self.update_tip("正在初始化文件...")
            tryfile.seek(0,0)

            self.source_file = tryfile
            self.source_bio = BytesIO()
            self.source_bio.write(self.source_file.read())
        
        # 加载到app中
        self.transfer = TransferV1(self.pure_file_name, self.source_bio, DATA_PROT_BYTES, DATA_PROT_V_1, CODE_PROT_SINGLE_CLR, qr_version=USING_VERSION)

        # 计算校验帧数量
        if USING_CHECK_FRQ == 0:
            self.check_frame_count = 0
        else:
            self.check_frame_count = math.ceil(self.transfer.total_batch_count / USING_CHECK_FRQ)

        self.update_tip(f"文件初始化完成, Meta帧 / {self.transfer.total_batch_count}/ {self.check_frame_count}帧")
    
    def _check_skip_frame_spinbox(self) -> bool:
        return True

    def _im_to_canvas_im(self, pil_im: Image) -> PhotoImage:
        pil_im = pil_im.resize((CANVAS_SIDE_SIZE, CANVAS_SIDE_SIZE))
        tk_im = ImageTk.PhotoImage(image=pil_im)
        return tk_im

    def _draw_im_to_canvas(self, im_tk: PhotoImage, pos:int = 0):
        if self.img_handles[self.buffer_index] != 0:
            self.qr_canvas.delete(self.img_handles[self.buffer_index])
        
        self.img_tk_buffer[self.buffer_index] = im_tk
        handle = self.qr_canvas.create_image(int(pos * CANVAS_SIDE_SIZE * CANVAS_SIDE_PADDING_RATE) ,0, image=im_tk, anchor=NW)
        self.img_handles[self.buffer_index] = handle
        self.buffer_index = (self.buffer_index + 1) % IMAGE_BUFFER_SIZE
        self.main_win.update_idletasks()

    # 补丁模式时，检查输入帧是否合法
    def _check_patchs_legal(self, patchs_str:str, total_frame:int) -> tuple:
        patchs_num = []
        try:
            patchs_num = sorted(set([int(x) for x in list(filter(lambda y:y.strip() != "", patchs_str.split(",")))]))

            if len(patchs_num) == 0:
                return (False, "无有效的补丁帧")
                
            illegal_num = list(filter(lambda x: x < 0 or x >= total_frame, patchs_num))

            if len(illegal_num) > 0:
                return (False, f"以下帧数超过合法帧[0,{total_frame}):{illegal_num}")
            
            return (True, patchs_num)
        except ValueError as e:
            messagebox.showerror("出错",f"解析补丁出错, ValueError:{e}")
            return (False, f"解析补丁出错, ValueError:{e}")
    
    # 处理可能的校验帧，不需要输出校验帧则返回(False,),需要输出则返回(True, data_im)
    def process_check_data(self) -> tuple:
        if self.transfer.patch_mode == True:
            return (False, "补丁模式不校验")
        
        if USING_CHECK_FRQ == 0:
            return (False, "用户指定不校验")

        # 剩下的是指定校验的情况，首先判断当前是否走到最后一帧，最后一帧必校验。然后判断是否是校验间隔的最后一帧，如是，也校验
        # 从当前帧，倒退到上一个与校验帧间隔取余为0的index，如果该列表长度仅为1，则与全1异或
        should_check = False
        if self.transfer.index == self.transfer.total_batch_count - 1:
            should_check = True
        elif (self.transfer.index + 1) % USING_CHECK_FRQ == 0:
            should_check = True

        if should_check == False:
            return (False, "非校验位置，不校验")
        
        # 获取源帧index列表
        src_frame_indexes = [self.transfer.index]
        tmp_index = self.transfer.index
        if USING_CHECK_FRQ > 1:
            tmp_index -= 1
            while tmp_index >= 0 and tmp_index % USING_CHECK_FRQ != (USING_CHECK_FRQ - 1):
                src_frame_indexes.append(tmp_index)
                tmp_index -= 1

        xor_res = bytes()
        
        min_data_len = 0
        if len(src_frame_indexes) == 1:
            xor_res = xor_with_one(self.transfer.gen_cur_frame_bytes(aimed_index=src_frame_indexes[0], pure_data=True))
            min_data_len = len(xor_res)

        else:
            ori_byteses = []
            for i in src_frame_indexes:
                ori_byteses.append(self.transfer.gen_cur_frame_bytes(aimed_index=i, pure_data=True))
            
            data_lens = [len(x) for x in ori_byteses]
            max_data_len = max(data_lens)
            min_data_len = min(data_lens)

            if (self.transfer.total_batch_count - 1) in src_frame_indexes:
                # 给尾帧补0
                for i in range(len(ori_byteses)):
                    if len(ori_byteses[i]) < max_data_len:
                        ori_byteses[i] += bytes(bytearray(max_data_len - len(ori_byteses[i])))
            
            # 计算异或校验帧
            xor_res= bytes_list_xor(ori_byteses)

        # 校验帧元数据区：开头4字节为0x19260817,后面跟一个字节，描述帧跨度：如0x05,即这一帧是临近5帧的异或结果，如果为0x01,说明是和全1异或的，即取反;再后面跟四字节数0x00000000,表示起始帧数，再后面跟0x0000,2字节数，表达末帧字节数，不够补0
        xor_res = 0x19260817.to_bytes(4, byteorder="big") + len(src_frame_indexes).to_bytes(1, byteorder="big") + src_frame_indexes[-1].to_bytes(4, byteorder="big") + min_data_len.to_bytes(2, byteorder="big") + xor_res

        im = self.transfer.gen_cur_qr_in_bytes(target_bytes=xor_res)
        return (True, im)

    def run_task(self):

        task_st = time.time()
        handled_data_frames = 0
        handled_check_frames = 0

        # 处理补丁模式
        if self.patch_frame_checkbtn_var.get() is True:
            check_res = self._check_patchs_legal(self.patch_frames_var.get(), self.transfer.total_batch_count)
            if check_res[0] is True:
                self.transfer.open_patchs(check_res[1])
            else:
                messagebox.showerror("补丁模式错误", check_res[1])
                return
        else:
            self.transfer.close_patchs()


        handshake_im = self.transfer.gen_handshake_qr()
        tk_im = self._im_to_canvas_im(handshake_im)
        self._draw_im_to_canvas(tk_im)
        time.sleep(1)
        has_next = True
        
        st = 0
        # 记录图像该显示在第几列，在单列模式下，始终显示在一个位置。所有列显示完了，再考虑是否暂停
        im_pos = 0
        while has_next is True or handled_check_frames < self.check_frame_count - 1:
            if self.call_stop is True:
                self.is_stoped = True
                return
            if self.is_pause is True:
                time.sleep(0.2)
                # print("暂停态")
                continue
            
            # 判断本次轮到数据帧还是校验帧
            # 校验帧条件：(校验开关打开 and 不是补丁模式) and ((是尾帧 or index是校验该当数,即index+1 对校验间隔取余为0) and 该当校验帧数比当前已handle校验帧数大1)
            is_check_frame = (USING_CHECK_FRQ > 0 and self.transfer.patch_mode == False) and ( (self.transfer.index == self.transfer.total_batch_count - 1 or (self.transfer.index + 1) % USING_CHECK_FRQ == 0) and  math.ceil(self.transfer.index / USING_CHECK_FRQ) == handled_check_frames + 1)

            data_im = 0
            if is_check_frame == False:
                # 生成QR码
                data_im = self.transfer.gen_cur_qr()
                has_next = (self.transfer.next_batch() != False)
            else:
                che_fr_res = self.process_check_data()
                if che_fr_res[0] == False:
                    raise Exception(f"生成校验帧意外错误 {che_fr_res}")
                data_im = che_fr_res[1]

            # 转换为tk图片
            tk_im = self._im_to_canvas_im(data_im)

            # 确保时间间隔确实是一帧显示时间
            # 准备再画第一帧时，计算时间是否足够
            if im_pos == 0:
                end  = time.time()

                # 决定帧间隔sleep
                frame_work_time = end - st
                frame_ideal_time = 1 / self.speed_var_int.get()
                time_break = frame_ideal_time - frame_work_time
                if time_break > 0:
                    time.sleep(time_break)    

            # 绘制到画布中
            self._draw_im_to_canvas(tk_im, im_pos)
            if is_check_frame:
                handled_check_frames += 1
            else:
                handled_data_frames += 1

            # 第一幅qr画好开始计时
            if im_pos == 0:
                st = time.time()
            im_pos = (im_pos + 1) % CANVAS_COL

            # 计算当前均速
            task_time = st - task_st
            total_trans_B = handled_data_frames * self.transfer.frame_pure_data_size_byte
            real_fps = (self.transfer.index + handled_check_frames) / task_time

            est_s = -1 if real_fps == 0 else (self.transfer.total_batch_count + self.check_frame_count - self.transfer.index - handled_check_frames) / real_fps
            self._set_file_speed_tip(total_trans_B / 1024 / task_time, fps=real_fps, est_s=est_s)

            
            # 获取当前帧
            # 更新任务信息
            self.update_tip(f"当前处理 [{handled_data_frames}/ {self.transfer.total_batch_count}]帧, [{handled_check_frames} / {self.check_frame_count}] 验")
            
            # 更新进度条
            self.progress_var.set((handled_data_frames + handled_check_frames) / (self.transfer.total_batch_count + self.check_frame_count) * 100)
        self.main_win.update_idletasks()
        time.sleep(5)
        self.reset_task()

class QrReceiverUI():
    REC_CANVAS_WIDTH = 600

    def __init__(self, root_win):
        self.rec_main_win = Toplevel(root_win)
        self.rec_main_win.title("任意传输接收器")

        self._prepare_components()

    def run(self):
        self.rec_main_win.deiconify()

    def _prepare_components(self):
        # 放置摄像头图像的canvas
        self.video_canvas = Canvas(self.rec_main_win, width=QrReceiverUI.REC_CANVAS_WIDTH, height=QrReceiverUI.REC_CANVAS_WIDTH, background="white")

        self.video_canvas.grid(column=0, row=0, columnspan=10, sticky=EW)

        # 状态显示label 
        self.state_var = StringVar()
        self.state_var.set("未开始")
        self.state_label = Label(self.rec_main_win)
        self.state_label.grid(column=0, row=1, columnspan=10)

        # 操作按钮
        self.start_btn = Button(self.rec_main_win, text="开始", command=self.on_start_btn)
        self.cancel_btn = Button(self.rec_main_win, text="取消", state="disabeld", command=self.on_cancel_btn)
        self.start_btn.grid(column=0, row=2, columnspan=5, sticky=EW)
        self.cancel_btn.grid(column=5, row=2, columnspan=5, sticky=EW)

        # 进度条
        self.progress_var = DoubleVar()
        self.progress_var.set(0)
        self.progress_bar = Progressbar(self.rec_main_win, maximum=100, mode="determinate", variable=self.progress_var)
        self.progress_bar.grid(column=0, row=3, columnspan=10, sticky=EW)

        # 进度Label
        self.progress_label_var = StringVar()
        self.progress_label_var.set("当前无任务")
        self.progress_label = Label(self.rec_main_win, textvariable=self.progress_label_var)
        self.progress_label.grid(column=0, row=4, columnspan=10, sticky=E)

        # 版权说明
        self.author_desc_label = Label(self.rec_main_win, text=AUTHOR_DESC)
        self.author_desc_label.grid(column=0, row=5, columnspan=10, sticky=E)


    def on_start_btn(self):
        pass

    def on_cancel_btn(self):
        pass

def main():
    global CANVAS_COL, USING_VERSION, USING_ENCODE, USING_CHECK_FRQ
    cols = -1
    user_version = -1
    user_encode = "base85"
    
    while cols == -1:
        i_cols = input(f"\n每屏二维码数(1~3)，默认为{CANVAS_COL}： ")
        if i_cols.strip() == "":
            cols = CANVAS_COL
        elif i_cols.strip() in [str(i) for i in range(1,4)]:
            cols = int(i_cols)
        else:
            print("请输入合法数字或直接回车取用默认值！")
            continue
    print(f"已采纳屏宽 {cols}")
    
    while user_version == -1:
        i_user_version = input(f"\n数据密度(15~31),越小越慢，越大识别率越低，默认为{USING_VERSION}： ")
        if i_user_version.strip() == "":
            user_version = USING_VERSION
        elif i_user_version.strip() in [str(i) for i in range(15,32)]:
            user_version = int(i_user_version)
        else:
            print("请输入合法数字或直接回车取用默认值！")
            continue
    print(f"已采纳版本{user_version}")

    a_encode = -1
    encodes = ["base85", "base64"]
    while True:
        a_encode = input(f"\n编码模式:\n1、base85 2、base64，默认为{USING_ENCODE}\n")
        if a_encode.strip() == "":
            user_encode = USING_ENCODE
            break
        elif a_encode.strip() in ["1","2"]:
            user_encode = encodes[int(a_encode.strip())]
            break
        else:
            print("请输入合法数字或直接回车取用默认值！")
            continue
    print(f"已选择编码 {user_encode}")

    user_check_frq = 0
    while True:
        user_check_frq = input(f"\n请选择校验间隔,取值范围 [1,128]， 校验间隔越大，纠错能力越差，0为不校验。默认为0。\n输入'c'查看估算纠错能力表：\n")
        user_check_frq = user_check_frq.strip()
        if user_check_frq.lower() == "c":
            show_check_table()
            continue
        elif user_check_frq == "":
            user_check_frq = 0
            print("采纳不校验")
            break
        elif user_check_frq.isdigit() == False:
            print("请输入合法整数")
            continue
        elif int(user_check_frq) < 1:
            user_check_frq = 0
            print("采纳不校验")
            break
        elif int(user_check_frq) > 128:
            user_check_frq = 128
            print("输入过大，按照128处理")
            break
        else:
            user_check_frq = int(user_check_frq)
            print(f"采纳校验间隔 {user_check_frq}")
            break

    CANVAS_COL = cols
    USING_VERSION = user_version
    USING_ENCODE = user_encode
    USING_CHECK_FRQ = user_check_frq

    ui = QrAnyTransUI()
    ui.run()


# 查看纠错能力估算表
def show_check_table():
    frq_list = [1,2,4,8,16,32,64,128]
    ori_err_frq = [0.5,0.2,0.1,0.05,0.02,0.01,0.005,0.001,0.0005,0.0001]

    print(f"{'校验间隔':5s} ", end="")
    for frame_frq in frq_list:
        print(f"{frame_frq:12d}", end="")
    print()
    
    print("原丢帧率\t\t\t\t\t\t纠正后仍有丢帧的概率")
    for err_frq in ori_err_frq:
        print(f"{err_frq * 100:9.3f}% ", end="")
        for frame_frq in frq_list:
            ecc = (err_frq * err_frq) * frame_frq * (frame_frq - 1) / 2
            if ecc < 1:
                print(f"{ecc * 100:11.4f}%", end="")
            else:
                print("%+12s" % ("Almost",), end="")
        print()


if __name__ == "__main__":
    main()