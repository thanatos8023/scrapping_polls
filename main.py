from typing import Optional, List, Dict, Set
from pydantic import BaseModel
from bson.objectid import ObjectId
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pymongo import MongoClient

from pprint import pprint

# set a 5-second connection timeout
client = MongoClient("mongodb://boksil:malang@localhost:27017/polls", serverSelectionTimeoutMS=5000)

try:
	print(client.version_info)
except Exception:
	print("Unable to connect to the server.")


app = FastAPI()


templates = Jinja2Templates(directory="templates")


# 여론조사 명칭
class Name(BaseModel):
	elect_category: str  # 선거구분
	elect_area: str      # 지역
	elect_name: str      # 선거명


# 조사일시
class PollTime(BaseModel):
	start: datetime
	end: datetime


# 표본 크기
class SampleSize(BaseModel):
	label: str       # 구분
	complete: int    # 조사완료 사례수(명)
	weighted: int    # 가중값 적용 기준 사례수(명)



# 여론조사 기본
class Basic(BaseModel):
	reg_idx: int                          # 등록 글번호
	name: Name                            # 여론조사 명칭
	client_name: str                      # 조사의뢰자
	subject: str                          # 조사기관명
	cosubject: Optional[str] = None       # 공동조사기관명
	poll_area: str                        # 조사지역
	#poll_time: List[PollTime]             # 조사일시 (2일 이상일 경우가 있음)
	poll_day: int                         # 조사일수
	#poll_duration: timedelta              # 조사시간
	poll_target: str                      # 조사대상



# 표본의 크기
class Sample(BaseModel):
	whole: SampleSize           # 전체
	gender: List[SampleSize]    # 성별
	age: List[SampleSize]       # 연령대별
	area: List[SampleSize]      # 지역별

	connect_sum: int            # 사용규모
	connect_OS: int             # 비적격 사례수: 결번
	connect_NE: int             # 비적격 사례수: 그 외의 비적격 사례수
	connect_U: int              # 접촉실패 사례수
	connect_R: int              # 접촉 후 거절 및 중도 이탕 사례수
	connect_I: int              # 접촉 후 응답완료 사례수

	mobile_ratio: float         # 무선 비율 (유선 비율 = 100 - 무선 비율)


# 여론조사 요약
class PollSummary(BaseModel):
	basicWeight_calc: Optional[str] = None            # 기본가중-산출방법
	basicWeight_apply: Optional[str] = None           # 기본가중-적용방법
	addWeight_calc: Optional[str] = None              # 추가가중-산출방법
	addWeight_apply: Optional[str] = None             # 추가가중-적용방법

	confidence: float                                 # 신뢰수준
	error_range: float                                # 오차범위

	media_category: str                               # 공표-보도 매체
	media_name: str                                   # 공표-보도 매체명
	media_datetime: datetime                          # 최초 공표-보도 지정일시


# 여론조사 결과
class Poll(BaseModel):
	sample_n: int                           # 사례수
	weighted_n: Optional[int] = None        # 가중값 적용기준 사례수
	response: List[Dict[str, float]]          # 응답 결과


class PollResult(BaseModel):
	label: str
	response: List[Dict[str, Poll]]



@app.get("/")
async def read_root():
	return {"Hello": "world"}


@app.get("/db")
async def read_db():
	sample = client.polls.test.find_one({'name': 'sample'})
	return sample['description']



@app.get("/input")
async def input(request: Request):
	context = {
		"request": request
	}
	return templates.TemplateResponse("input.html", context)


@app.post("/input")
async def regist_polls(
	request: Request, 
	# Basic information
	reg_idx: int = Form(...),
	elect_category: str = Form(...),
	elect_area: str = Form(...),
	elect_name: str = Form(...),
	client_name: str = Form(...),
	subject: str = Form(...),
	cosubject: Optional[str] = Form(None),
	poll_area: str = Form(...),
	poll_day: str = Form(...),
	poll_target: str = Form(...),

	# Sample size information
	whole_orig: int = Form(...),
	whole_weight: int = Form(...),
	man_orig: int = Form(...),
	man_weight: int = Form(...),
	woman_orig: int = Form(...),
	woman_weight: int = Form(...),
	_20_orig: int = Form(...),
	_20_weight: int = Form(...),
	_30_orig: int = Form(...),
	_30_weight: int = Form(...),
	_40_orig: int = Form(...),
	_40_weight: int = Form(...),
	_50_orig: int = Form(...),
	_50_weight: int = Form(...),
	_60_orig: int = Form(...),
	_60_weight: int = Form(...),

	# Sampling method
	sample_frame: str = Form(...),
	sample_size: int = Form(...),
	sample_method: str = Form(...),
	mobile_ratio: float = Form(...),
	sample_R: int = Form(...),
	sample_I: int = Form(...),
	sample_sum: int = Form(...),
	contact_ratio: float = Form(...),
	response_ratio: float = Form(...),

	# Poll summary
	weight1_calc: Optional[str] = Form(None),
	weight1_apply: Optional[str] = Form(None),
	weight2_calc: Optional[str] = Form(None),
	weight2_apply: Optional[str] = Form(None),
	trust: float = Form(...),
	error: float = Form(...),
	publish_media: str = Form(...),
	publisher: str = Form(...),
	publish_date: datetime = Form(...),
):
	form_data = await request.form()

	# Update time
	starttimes = []
	endtimes = []

	# Area samples
	areas_name = []
	areas_orig = []
	areas_weight = []

	# Optional keys search
	for key in form_data:
		# Poll times
		if key.startswith("polltime_start_"):
			starttimes.append(form_data[key])
		elif key.startswith("polltime_end_"):
			endtimes.append(form_data[key])

		# Area sample size
		if key.startswith("area_orig_"):
			areas_orig.append(form_data[key])
		elif key.startswith("area_weight_"):
			areas_weight.append(form_data[key])
		elif key.startswith("area_name_"):
			areas_name.append(form_data[key])

	
	poll_time = [{'start': start, 'end': end} for start, end in zip(starttimes, endtimes)]

	# Calculate duration
	poll_duration = calc_duration(poll_time)


	areas_sample = [{"area": name, "original": orig, "weighted": weight} for name, orig, weight in zip(areas_name, areas_orig, areas_weight)]


	context = {
		# Basic information
		"basic": {
			"reg_idx": reg_idx,
			"elect_category": elect_category,
			"elect_area": elect_area,
			"elect_name": elect_name,
			"client_name": client_name,
			"subject": subject,
			"cosubject": cosubject,
			"poll_area": poll_area,
			"poll_time": poll_time,
			"poll_duration": poll_duration,
			"poll_day": poll_day,
			"poll_target": poll_target
		},

		# Sample size information
		"sampleSize": {
			"whole": {
				"original": whole_orig,
				"weighted": whole_weight
			},
			"gender": {
				"original": {
					"male": man_orig,
					"female": woman_orig
				},
				"weighted": {
					"male": man_weight,
					"female": woman_weight
				}
			},
			"age": {
				"original": {
					"_20": _20_orig,
					"_30": _30_orig,
					"_40": _40_orig,
					"_50": _50_orig,
					"_60": _60_orig
				},
				"weighted": {
					"_20": _20_weight,
					"_30": _30_weight,
					"_40": _40_weight,
					"_50": _50_weight,
					"_60": _60_weight
				}
			},
			"area": areas_sample
		},

		# Sampling method
		"sampleMethod": {
			"selection": {
				"frame": sample_frame,
				"size": sample_size,
				"method": sample_method
			},
			"contact": {
				"mobileRatio": mobile_ratio,
				"R": sample_R,
				"I": sample_I,
				"sum": sample_sum,
				"contactRatio": contact_ratio,
				"responseRatio": response_ratio
			}
		},

		# Poll summary
		"summary": {
			"weighting": {
				"standard": {
					"calculation": weight1_calc,
					"apply": weight1_apply
				},
				"additional": {
					"calculation": weight2_calc,
					"apply": weight2_apply
				}
			},
			"standardDeviation": {
				"trust": trust,
				"error": error
			},
			"publish": {
				"media": publish_media,
				"publisher": publisher,
				"date": publish_date
			}
		}
	}

	return RedirectResponse("/input/{}/".format(reg_idx))



# Detail polls result
@app.post("/input/{poll_id}/")
async def input_detail(poll_id: int, request: Request):
	context = {
		"request": request
	}
	return templates.TemplateResponse("detail.html", context)


# Test page
@app.get("/input/{poll_id}/")
async def input_detail_test(poll_id: int, request: Request):
	context = {
		"request": request
	}
	return templates.TemplateResponse("detail.html", context)



def calc_duration(times):
	delta_list = []
	for time_dict in times:
		start = datetime.strptime(time_dict['start'], "%Y-%m-%dT%H:%M")
		end = datetime.strptime(time_dict['end'], "%Y-%m-%dT%H:%M")
		diff = end - start
		hour = diff.seconds // 3600
		delta_list.append(hour)
	return sum(delta_list)