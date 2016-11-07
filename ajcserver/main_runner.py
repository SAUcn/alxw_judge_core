#!/usr/bin/env python
# coding=utf-8

import os
import config
import sys
import shutil
import subprocess
import codecs
import logging
import socket
import shlex
import time
import json
import threading
import traceback
import signal
import MySQLdb
from db import run_sql
from Queue import Queue






'''Socket List'''
socks = []
for i in range(config.count_thread):
    socks.append('/home/AJC/runtime/%d.sock' % i)






if 0 != int(os.popen("id -u").read()):
    logging.error("please run this program as root!")
    sys.exit(-1)

def SendAndTest(sock, runcfg):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(sock)
    client.send(json.dumps(runcfg))
    ret = json.loads(client.recv(1024))
    client.close()
    return ret

def low_level():
    pass
    """
    弃用
    try:
        os.setuid(int(os.popen("id -u %s" % "nobody").read()))
    except:
        pass
    """

def kill_proc(p):
    try:
        p.kill()
        print 'After few second(s) so we kill thr compiler ...'
    except:
        pass

# 初始化队列
q = Queue(config.queue_size)
# 创建数据库锁，保证一个时间只能一个程序都写数据库
dblock = threading.Lock()


def update_solution_status(solution_id, status='Waiting'):
    sql = "update Record set `rid`='%s',`result`='Waiting' where `id`='%s'" % (solution_id, solution_id)
    run_sql(sql)


def update_compile_info(solution_id, result):
    sql = "update Record set `compileinfo`='%s' where `id`='%s'" % (MySQLdb.escape_string(result), solution_id)
    run_sql(sql)

def update_result(result, user, problem):
    re_result_code = {
        0:"Waiting",
        1:"Accepted",
        2:"Time Limit Exceeded",
        3:"Memory Limit Exceeded",
        4:"Wrong Answer",
        5:"Runtime Error",
        6:"Output Limit Exceeded",
        7:"Compile Error",
        8:"Presentation Error",
        11:"System Error",
        12:"Judging",
    }
    sql = "update Record set `result`='%s',`long`='%dMS',`memory`='%dK' where `id`='%s'" % (re_result_code[result['result']], result['take_time'], result['take_memory'], result['solution_id'])
    run_sql(sql)
    if result['result']== 1:
        t_res = run_sql("select distinct oid from Record where `user`='%s' and result='Accepted'" % user)
        t_res = map(lambda ptr:ptr[0], t_res)
        run_sql("update Users set `plist`='%s',`ac`='%d' where `user`='%s'" % (' '.join(t_res), len(t_res), user))
        logging.info('Solved problem list updated')
        run_sql('update AJC_Problem set accepted=accepted+1,submissions=submissions+1 where id=%s' % problem)
    else:
        run_sql('update AJC_Problem set submissions=submissions+1 where id=%s' % problem)


def judge(solution_id, problem_id, data_count, time_limit, mem_limit, program_info, result_code, language, sock):
    low_level()
    '''评测编译类型语言'''
    max_mem = 0
    max_time = 0
    time_limit = int(time_limit)
    mem_limit = int(mem_limit)
    if language.lower() in ["java", 'python2', 'python3', 'ruby', 'perl']:
        time_limit = time_limit * 2
        mem_limit = mem_limit * 2
    for i in range(data_count):
        ret = judge_one_mem_time(
            solution_id,
            problem_id,
            i + 1,
            int(time_limit) + 10,
            int(mem_limit),
            language,
            sock)
        if ret == False:
            continue
        if ret['result'] == 5:
            program_info['result'] = result_code["Runtime Error"]
            return program_info
        elif ret['result'] == 2:
            program_info['result'] = result_code["Time Limit Exceeded"]
            program_info['take_time'] = time_limit + 10
            return program_info
        elif ret['result'] == 3:
            program_info['result'] = result_code["Memory Limit Exceeded"]
            program_info['take_memory'] = mem_limit
            return program_info
        if max_time < ret["timeused"]:
            max_time = ret['timeused']
        if max_mem < ret['memoryused']:
            max_mem = ret['memoryused']
        result = judge_result(problem_id, solution_id, i + 1)
        if result == False:
            continue
        if result == "Wrong Answer" or result == "Output limit":
            program_info['result'] = result_code[result]
            break
        elif result == 'Presentation Error':
            program_info['result'] = result_code[result]
        elif result == 'Accepted':
            if program_info['result'] != 'Presentation Error':
                program_info['result'] = result_code[result]
        else:
            logging.error("judge did not get result")
    program_info['take_time'] = max_time
    program_info['take_memory'] = max_mem
    return program_info


def judge_one_mem_time(solution_id, problem_id, data_num, time_limit, mem_limit, language, sock):
    low_level()
    '''评测一组数据'''
    language = language.lower()
    if language == 'java':
        cmd = '/usr/bin/java -Xms%dM -Xmx%dM -Djava.security.manager -Djava.security.policy=/home/AJC/ajcserver/java.policy -cp %s Main' % (int(mem_limit/1024), int(mem_limit/1024),
            os.path.join(config.work_dir,
                         str(solution_id)))
        main_exe = shlex.split(cmd)
    elif language == 'python2':
        cmd = 'python2 %s' % (
            os.path.join(config.work_dir,
                         str(solution_id),
                         'main.pyc'))
        main_exe = shlex.split(cmd)
    elif language == 'python3':
        cmd = 'python3 %s' % (
            os.path.join(config.work_dir,
                         str(solution_id),
                         '__pycache__/main.cpython-33.pyc'))
        main_exe = shlex.split(cmd)
    elif language == 'lua':
        cmd = "lua %s" % (
            os.path.join(config.work_dir,
                         str(solution_id),
                         "main"))
        main_exe = shlex.split(cmd)
    elif language == "ruby":
        cmd = "ruby %s" % (
            os.path.join(config.work_dir,
                         str(solution_id),
                         "main.rb"))
        main_exe = shlex.split(cmd)
    elif language == "perl":
        cmd = "perl %s" % (
            os.path.join(config.work_dir,
                         str(solution_id),
                         "main.pl"))
        main_exe = shlex.split(cmd)
    else:
        main_exe = [os.path.join(config.work_dir, str(solution_id), 'main'), ]
    '''远程调用'''
    input_path = os.path.join(config.data_dir, str(problem_id), 'data%s.in' % data_num)
    output_path = os.path.join(config.work_dir, str(solution_id), 'out%s.txt' % data_num)
    error_path = os.path.join(config.work_dir, str(solution_id), 'err%s.txt' % data_num)
    file(output_path, 'w').close()
    file(error_path, 'w').close()
    if language == 'java':
        runcfg = {
            'args': main_exe,
            'fd_in': input_path,
            'fd_out': output_path,
            'fd_err': error_path,
            'timelimit': time_limit,
            'memorylimit': mem_limit,
            'java' : True
        }
    else:
        runcfg = {
            'args': main_exe,
            'fd_in': input_path,
            'fd_out': output_path,
            'fd_err': error_path,
            'timelimit': time_limit,
            'memorylimit': mem_limit,
            'java' : False,
            'trace': True,
            'calls': config.white_list,
            'files': {}
        }
    low_level()
    # rst = lorun.run(runcfg)
    rst = SendAndTest(sock, runcfg)
    rst['memoryused'], rst['result'] = fix_java_mis_judge(error_path, rst['result'], rst['memoryused'], mem_limit)
    logging.debug(rst)
    return rst

def fix_java_mis_judge(stderr, res_now, mem_now, mem_limit):
    err_str = ''
    result = res_now
    memory = mem_now
    try:
        with open(stderr, 'r') as fp:
            err_str = fp.read()
            fp.close()
    except:
        return memory, result
    if 'Exception' in err_str:
        result = 5
    if 'java.lang.OutOfMemoryError' in err_str:
        result = 3
        memory = mem_limit + 10
    if 'Could not create' in err_str:
        result = 5
    return memory, result

def judge_result(problem_id, solution_id, data_num):
    low_level()
    '''对输出数据进行评测'''
    logging.debug("Judging result")
    correct_result = os.path.join(
        config.data_dir, str(problem_id), 'data%s.out' %
        data_num)
    user_result = os.path.join(
        config.work_dir, str(solution_id), 'out%s.txt' %
        data_num)
    try:
        correct = file(
            correct_result).read(
            ).replace(
                '\r',
                '').rstrip(
                )  # 删除\r,删除行末的空格和换行
        user = file(user_result).read().replace('\r', '').rstrip()
    except:
        return False
    if correct == user:  # 完全相同:AC
        return "Accepted"
    if correct.split() == user.split():  # 除去空格,tab,换行相同:PE
        return "Presentation Error"
    if correct in user:  # 输出多了
        return "Output limit"
    return "Wrong Answer"  # 其他WA


def get_problem_limit(problem_id):
    select_sql = "select `time`,`memory` from `AJC_Problem` where `id`='%s'" % problem_id
    dblock.acquire()
    feh = run_sql(select_sql)
    dblock.release()
    if feh is not None:
        try:
            time_t,memory_t  = feh[0]
        except:
            logging.error("1 cannot get code of runid %s" % solution_id)
            return False
    return time_t,memory_t


def run(problem_id, solution_id, language, data_count, user_id, sock):
    low_level()
    '''获取程序执行时间和内存'''
    time_limit, mem_limit = get_problem_limit(problem_id)
    program_info = {
        "solution_id": solution_id,
        "problem_id": problem_id,
        "take_time": 0,
        "take_memory": 0,
        "user_id": user_id,
        "result": 0,
    }
    result_code = {
        "Waiting": 0,
        "Accepted": 1,
        "Time Limit Exceeded": 2,
        "Memory Limit Exceeded": 3,
        "Wrong Answer": 4,
        "Runtime Error": 5,
        "Output limit": 6,
        "Compile Error": 7,
        "Presentation Error": 8,
        "System Error": 11,
        "Judging": 12,
    }
    '''
    我不会这么玩的－－
    if check_dangerous_code(solution_id, language) == False:
        program_info['result'] = result_code["Runtime Error"]
        return program_info
    '''
    compile_result = compileCode(solution_id, language)
    if compile_result is False:  # 编译错误
        program_info['result'] = result_code["Compile Error"]
        return program_info
    if data_count == 0:  # 没有测试数据
        program_info['result'] = result_code["System Error"]
        return program_info
    result = judge(
        solution_id,
        problem_id,
        data_count,
        time_limit,
        mem_limit,
        program_info,
        result_code,
        language,
        sock)
    logging.debug(result)
    return result


def compileCode(solution_id, language):
    low_level()
    '''将程序编译成可执行文件'''
    language = language.lower()
    dir_work = os.path.join(config.work_dir, str(solution_id))
    build_cmd = {
        "gcc": "gcc main.c -o main -fno-asm --static -Wall -lm -std=c99 -DONLINE_JUDGE",
        "g++": "g++ main.cpp -o main -fno-asm --static -Wall -lm -std=c++0x -DONLINE_JUDGE",
        "java": "javac -J-Xms32m -J-Xmx256m Main.java",
        "ruby": "reek main.rb",
        "perl": "perl -c main.pl",
        "pascal": 'fpc main.pas -O2 -Co -Ct -Ci',
        "go": '/opt/golang/bin/go build -ldflags "-s -w"  main.go',
        "lua": 'luac -o main main.lua',
        "python2": 'python2 -m py_compile main.py',
        "python3": 'python3 -m py_compile main.py',
        "haskell": "ghc -o main main.hs",
    }
    if language not in build_cmd.keys():
        return False
    '''
    command = Command("cd %s; %s" % (dir_work, build_cmd[language]))
    status, out, err = command.run(timeout=5, shell=True)
    print status, out, err
    '''
    p = subprocess.Popen(
        build_cmd[language],
        shell=True,
        cwd=dir_work,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True)
    timer = threading.Timer(config.compile_timeout, kill_proc, [p])
    try:
        timer.start()
        out, err = p.communicate()  # 获取编译错误信息
    finally:
        timer.cancel()
    '''
    err_txt_path = os.path.join(config.work_dir, str(solution_id), 'error.txt')
    f = file(err_txt_path, 'w')
    f.write(err)
    f.write(out)
    f.close()
    '''
    if p.returncode == 0:  # 返回值为0,编译成功
        return True
    '''
    if status == 0:
        return True
    '''
    update_compile_info(solution_id, err + out)  # 编译失败,更新题目的编译错误信息
    return False


'''虽然很扯淡的危险检测，但是我还是留下来了－－'''
def check_dangerous_code(solution_id, language):
    if language in ['python2', 'python3']:
        code = file('/work/%s/main.py' % solution_id).readlines()
        support_modules = [
            're',  # 正则表达式
            'sys',  # sys.stdin
            'string',  # 字符串处理
            'scanf',  # 格式化输入
            'math',  # 数学库
            'cmath',  # 复数数学库
            'decimal',  # 数学库，浮点数
            'numbers',  # 抽象基类
            'fractions',  # 有理数
            'random',  # 随机数
            'itertools',  # 迭代函数
            'functools',
            #Higher order functions and operations on callable objects
            'operator',  # 函数操作
            'readline',  # 读文件
            'json',  # 解析json
            'array',  # 数组
            'sets',  # 集合
            'queue',  # 队列
            'types',  # 判断类型
        ]
        for line in code:
            if line.find('import') >= 0:
                words = line.split()
                tag = 0
                for w in words:
                    if w in support_modules:
                        tag = 1
                        break
                if tag == 0:
                    return False
        return True
    if language in ['gcc', 'g++']:
        try:
            code = file('/work/%s/main.c' % solution_id).read()
        except:
            code = file('/work/%s/main.cpp' % solution_id).read()
        if code.find('system') >= 0:
            return False
        return True
#    if language == 'java':
#        code = file('/work/%s/Main.java'%solution_id).read()
#        if code.find('Runtime.')>=0:
#            return False
#        return True
    if language == 'go':
        code = file('/work/%s/main.go' % solution_id).read()
        danger_package = [
            'os', 'path', 'net', 'sql', 'syslog', 'http', 'mail', 'rpc', 'smtp', 'exec', 'user',
        ]
        for item in danger_package:
            if code.find('"%s"' % item) >= 0:
                return False
        return True


def put_task_into_queue():
    '''循环扫描数据库,将任务添加到队列'''
    while True:
        q.join()  # 阻塞程序,直到队列里面的任务全部完成
        sql = "select `id`,`tid`,`user`,`contest`,`lang`,`code` from Record where `rid`='__' and oj='AJC'"
        data = run_sql(sql)
        time.sleep(0.2)  # 延时0.2秒,防止因速度太快不能获取代码
        for i in data:
            solution_id, problem_id, user_id, contest_id, pro_lang, code = i
            put_code(solution_id, problem_id, pro_lang, code)
            task = {
                "solution_id": solution_id,
                "problem_id": problem_id,
                "contest_id": contest_id,
                "user_id": user_id,
                "pro_lang": pro_lang,
            }
            q.put(task)
            dblock.acquire()
            update_solution_status(solution_id)
            dblock.release()
        time.sleep(0.5)


def clean_work_dir(solution_id):
    '''清理word目录，删除临时文件'''
    dir_name = os.path.join(config.work_dir, str(solution_id))
    shutil.rmtree(dir_name)



def get_data_count(problem_id):
    '''获得测试数据的个数信息'''
    full_path = os.path.join(config.data_dir, str(problem_id))
    try:
        files = os.listdir(full_path)
    except OSError as e:
        logging.error(e)
        return 0
    count = 0
    for item in files:
        if item.endswith(".in") and item.startswith("data"):
            count += 1
    return count


def worker(sock):
    '''工作线程，循环扫描队列，获得评判任务并执行'''
    logging.info("Work for socket %s" % (sock))
    while True:
        if q.empty() is True:  # 队列为空，空闲
            logging.info("%s idle" % (threading.current_thread().name))
        task = q.get()  # 获取任务，如果队列为空则阻塞
        solution_id = task['solution_id']
        problem_id = task['problem_id']
        language = task['pro_lang']
        user_id = task['user_id']
        data_count = get_data_count(task['problem_id'])  # 获取测试数据的个数
        logging.info("judging %s" % solution_id)
        result = run(
            problem_id,
            solution_id,
            language,
            data_count,
            user_id,
            sock)  # 评判
        logging.info(
            "%s result %s" % (
                result[
            'solution_id'],
                result[
                    'result']))
        dblock.acquire()
        update_result(result, user_id, problem_id)  # 将结果写入数据库
        dblock.release()
        if config.auto_clean:  # 清理work目录
            clean_work_dir(result['solution_id'])
        q.task_done()  # 一个任务完成


def put_code(solution_id, problem_id, pro_lang, code):
    '''获取代码并写入work目录下对应的文件'''
    file_name = {
        "gcc": "main.c",
        "g++": "main.cpp",
        "java": "Main.java",
        'ruby': "main.rb",
        "perl": "main.pl",
        "pascal": "main.pas",
        "go": "main.go",
        "lua": "main.lua",
        'python2': 'main.py',
        'python3': 'main.py',
        "haskell": "main.hs"
    }
    try:
        work_path = os.path.join(config.work_dir, str(solution_id))
        low_level()
        os.mkdir(work_path)
    except OSError as e:
        if str(e).find("exist") > 0:  # 文件夹已经存在
            pass
        else:
            logging.error(e)
            return False
    try:
        real_path = os.path.join(
            config.work_dir,
            str(solution_id),
            file_name[pro_lang.lower()])
    except KeyError as e:
        logging.error(e)
        return False
    try:
        low_level()
        f = codecs.open(real_path, 'w', 'utf-8')
        try:
            f.write(code)
        except:
            logging.error("%s not write code to file" % solution_id)
            f.close()
            return False
        f.close()
    except OSError as e:
        logging.error(e)
        return False
    return True


def start_work_thread():
    '''开启工作线程'''
    for i in range(config.count_thread):
        t = threading.Thread(target=worker,args=(socks[i],))
        t.deamon = True
        t.start()


def start_get_task():
    '''开启获取任务线程'''
    t = threading.Thread(target=put_task_into_queue, name="get_task")
    t.deamon = True
    t.start()


def main():
    low_level()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s --- %(message)s',)
    start_get_task()
    start_work_thread()

if __name__ == '__main__':
    main()
