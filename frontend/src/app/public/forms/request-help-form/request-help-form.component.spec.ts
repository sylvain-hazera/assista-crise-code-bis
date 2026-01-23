import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RequestHelpFormComponent } from './request-help-form.component';

describe('RequestHelpFormComponent', () => {
  let component: RequestHelpFormComponent;
  let fixture: ComponentFixture<RequestHelpFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RequestHelpFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(RequestHelpFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
